import os
import re
import logging
import requests
import time # Add time import for polling
from pydantic import Field, validator
from typing import List, Dict, Any
from datetime import datetime, timezone, timedelta
from apify_client import ApifyClient

from proconfig.widgets.base import WIDGETS, BaseWidget

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@WIDGETS.register_module()
class YouTubeChannelVideos(BaseWidget):
    """
    Fetches recent videos from a YouTube channel and optionally retrieves their download links.
    Requires APIFY_API_KEY environment variable.
    Uses Apify actors for both channel scraping and video downloading.
    Includes caching for download links.
    """
    CATEGORY = "Custom Widgets/YouTube"
    NAME = "YouTube Channel Videos & Downloader"

    class InputsSchema(BaseWidget.InputsSchema):
        channel_urls: List[str] = Field(["https://www.youtube.com/@yttalkjun"], description="YouTube频道URL列表, 例如: [\"https://www.youtube.com/@channelname1\", \"https://www.youtube.com/@channelname2\"]")
        max_videos_per_channel: int = Field(1, description="每个频道要获取的最新视频数量 (1-10)", ge=1, le=10)
        time_filter: int = Field(24, description="只返回多少小时内上传的视频 (0表示不过滤)", ge=0)
        # Download options
        download_videos: bool = Field(False, description="是否获取视频下载链接")
        download_resolution: str = Field("360", description="视频分辨率 (720, 480, 360, etc.)")
        use_residential_proxy: bool = Field(False, description="下载时是否使用住宅代理")
        proxy_country: str = Field("US", description="下载时代理服务器国家/地区代码")
        force_refresh_cache: bool = Field(False, description="强制刷新下载链接缓存")
        # Transcription options
        transcribe_videos: bool = Field(False, description="是否对下载的视频进行转录")
        # min_speakers: int = Field(-1, description="转录时最小说话人数 (-1 表示自动)") # TODO: Add later if needed
        # max_speakers: int = Field(-1, description="转录时最大说话人数 (-1 表示自动)") # TODO: Add later if needed

        @validator('download_resolution')
        def validate_download_resolution(cls, v):
            valid_resolutions = ["2160", "1440", "1080", "720", "480", "360", "240", "144"]
            if v not in valid_resolutions:
                raise ValueError(f"分辨率必须是以下之一: {', '.join(valid_resolutions)}")
            return v

    class OutputsSchema(BaseWidget.OutputsSchema):
        videos: List[dict] = Field([], description="符合条件的视频列表, 可能包含下载信息")
        filtered_count: int = Field(0, description="时间过滤后的视频数量")
        total_fetched: int = Field(0, description="获取的视频总数")
        error: str = Field(None, description="执行过程中发生的错误信息")

    # --- Helper methods from YouTubeDownloaderWidget (adapted) ---

    def _get_or_create_store(self, client):
        """获取或创建key_value_store用于缓存下载链接"""
        try:
            store = client.key_value_stores().get_or_create(name="youtube-downloader-cache")
            logging.info(f"Using KV store: {store.get('id', 'N/A')}")
            return store["id"]
        except Exception as e:
            logging.error(f"Failed to get or create KV store: {repr(e)}")
            raise  # Re-raise the exception to be caught by the main execute block

    def _get_link_from_store(self, client, store_id, youtube_url, resolution):
        """从store中获取缓存的下载链接"""
        MAP_KEY = f"youtube_link_map_{resolution}"
        try:
            record = client.key_value_store(store_id).get_record(MAP_KEY)
            link_map = record.get("value", {}) if record else {}
            return link_map.get(youtube_url)
        except Exception as e:
            # Log non-critical errors, return None to indicate cache miss
            logging.warning(f"从KV存储获取链接失败 (non-critical): {repr(e)}")
            return None

    def _save_link_to_store(self, client, store_id, youtube_url, download_url, resolution):
        """保存下载链接到store"""
        MAP_KEY = f"youtube_link_map_{resolution}"
        try:
            record = client.key_value_store(store_id).get_record(MAP_KEY)
            link_map = record.get("value", {}) if record else {}
            link_map[youtube_url] = download_url
            client.key_value_store(store_id).set_record(MAP_KEY, link_map)
            logging.info(f"成功缓存下载链接: {youtube_url} ({resolution})")
            return True
        except Exception as e:
            logging.error(f"保存链接映射失败: {repr(e)}")
            return False # Indicate failure

    def _is_url_valid(self, url):
        """检查URL是否可以通过HEAD请求访问"""
        if not url:
            return False
        try:
            response = requests.head(url, timeout=10, allow_redirects=True)
            # Consider redirects (3xx) and success (2xx) as valid
            is_valid = 200 <= response.status_code < 400
            logging.info(f"URL check for {url}: status {response.status_code}, valid: {is_valid}")
            return is_valid
        except requests.exceptions.RequestException as e:
            logging.warning(f"URL有效性检查失败 for {url}: {repr(e)}")
            return False
        except Exception as e: # Catch any other unexpected errors
            logging.error(f"Unexpected error during URL validation for {url}: {repr(e)}")
            return False

    # --- Transcription Helper ---
    def _get_transcription(self, download_url: str, whisperx_base_url: str, poll_interval: int = 5, max_polls: int = 60): # 5s interval, 5 min timeout
        """Submits a video URL for transcription and polls for the result."""
        if not whisperx_base_url:
            return "error", "WHISPERX_MODEL_URL not configured."

        run_url = f"{whisperx_base_url}/run"
        result_url = f"{whisperx_base_url}/get_result"

        # Use JSON content type
        headers = {'Content-Type': 'application/json'}
        submit_payload = {
            "voice_url": download_url,
            "min_speakers": -1, # Using default values as per user request
            "max_speakers": -1
        }

        try:
            # 1. Submit job
            logging.info(f"Submitting transcription job for: {download_url} to {run_url}")
            # --- Debug Log ---
            logging.info(f"Submit Request URL: {run_url}")
            logging.info(f"Submit Request Headers: {headers}")
            logging.info(f"Submit Request Payload: {submit_payload}")
            # --- End Debug Log ---
            # Send payload as JSON using the 'json' parameter
            submit_response = requests.post(run_url, json=submit_payload, headers=headers, timeout=30)
            # submit_response.raise_for_status() # Check status code manually

            # Check submission status code
            if submit_response.status_code in [200, 201, 202]: # OK, Created, Accepted
                try:
                    submit_data = submit_response.json()
                    task_id = submit_data.get("task_id")
                    if not task_id:
                        logging.error(f"Transcription submission failed: No task_id received. Status: {submit_response.status_code}, Response: {submit_response.text}")
                        return "error", f"Transcription submission failed: No task_id. Status: {submit_response.status_code}, Response: {submit_response.text[:200]}" # Limit response size
                    logging.info(f"Transcription job submitted. Task ID: {task_id}. Status: {submit_response.status_code}")
                except requests.exceptions.JSONDecodeError:
                     logging.error(f"Transcription submission failed: Invalid JSON response. Status: {submit_response.status_code}, Response: {submit_response.text}")
                     return "error", f"Transcription submission failed: Invalid JSON. Status: {submit_response.status_code}, Response: {submit_response.text[:200]}"
            else:
                 logging.error(f"Transcription submission failed. Status: {submit_response.status_code}, Response: {submit_response.text}")
                 return "error", f"Transcription submission failed. Status: {submit_response.status_code}, Response: {submit_response.text[:200]}"

            # 2. Poll for result
            result_payload = {"task_id": task_id}
            for attempt in range(max_polls):
                logging.info(f"Polling transcription result for task {task_id} (Attempt {attempt + 1}/{max_polls})")
                time.sleep(poll_interval)
                try:
                    # --- Debug Log ---
                    logging.info(f"Poll Request URL: {result_url}")
                    logging.info(f"Poll Request Headers: {headers}")
                    logging.info(f"Poll Request Payload: {result_payload}")
                    # --- End Debug Log ---
                    # Send payload as JSON using the 'json' parameter
                    result_response = requests.post(result_url, json=result_payload, headers=headers, timeout=30)
                    # result_response.raise_for_status() # Check status code manually

                    # --- Check Poll Status Code ---
                    if result_response.status_code == 200: # OK - potentially final state
                        try:
                            result_data = result_response.json()
                            status = result_data.get("status")

                            if status == "SUCCESS":
                                logging.info(f"Transcription complete (API status {status}) for task {task_id}")
                                # Return the full result data which should contain the transcript
                                return "success", result_data
                            elif status == "FAILED":
                                logging.error(f"Transcription failed (API status {status}) for task {task_id}. Response: {result_data}")
                                error_message = result_data.get("error", "Unknown transcription failure reason.")
                                return "error", f"Transcription failed: {error_message}"
                            elif status == "RUNNING":
                                logging.info(f"Transcription still processing (API status {status}) for task {task_id}...")
                                continue # Continue polling
                            else:
                                # Unknown status in a 200 OK response
                                logging.warning(f"Unexpected API status '{status}' in 200 OK response for task {task_id}. Response: {result_data}. Assuming processing continues...")
                                continue # Continue polling, but log warning

                        except requests.exceptions.JSONDecodeError:
                            logging.error(f"Polling error: Invalid JSON response. Status: 200, Response: {result_response.text}")
                            # Treat as temporary error and continue polling. If persistent, will eventually time out.
                            continue

                    elif result_response.status_code == 202: # Accepted - definitely still processing
                         logging.info(f"Transcription still processing (HTTP 202 Accepted) for task {task_id}...")
                         continue # Continue polling

                    elif result_response.status_code == 404: # Not Found
                         logging.error(f"Polling error: Task ID {task_id} not found (HTTP 404). It might have expired or is invalid.")
                         return "error", f"Polling error: Task ID {task_id} not found (404)."

                    else: # Handle other 4xx/5xx errors
                        logging.error(f"Polling error for task {task_id}. Status: {result_response.status_code}, Response: {result_response.text}")
                        # Decide if this is retryable? For now, treat as fatal poll error.
                        return "error", f"Polling error. Status: {result_response.status_code}, Response: {result_response.text[:200]}"

                except requests.exceptions.Timeout:
                    logging.warning(f"Polling request timed out for task {task_id}. Retrying...")
                    continue # Retry polling
                except requests.exceptions.RequestException as poll_e:
                    logging.error(f"Polling connection error for task {task_id}: {repr(poll_e)}")
                    # Potentially retry connection errors a few times? For now, treat as fatal poll error.
                    return "error", f"Polling connection error: {repr(poll_e)}"

        except requests.exceptions.Timeout:
             logging.error(f"Transcription submission timed out for URL: {download_url}")
             return "error", "Transcription submission timed out."
        except requests.exceptions.RequestException as submit_e:
            logging.error(f"Transcription submission failed for URL {download_url}: {repr(submit_e)}")
            # Log response body if available
            error_body = ""
            if hasattr(submit_e, 'response') and submit_e.response is not None:
                try:
                    error_body = submit_e.response.text
                except Exception:
                    error_body = "(Could not read response body)"
            logging.error(f"Submission error response body: {error_body}")
            return "error", f"Transcription submission error: {repr(submit_e)}"
        except Exception as e:
            logging.error(f"Unexpected error during transcription for {download_url}: {repr(e)}")
            return "error", f"Unexpected transcription error: {repr(e)}"

    # --- Main Execution Logic ---

    def execute(self, environ, config):
        channel_urls = config.channel_urls
        max_videos_per_channel = config.max_videos_per_channel
        time_filter = config.time_filter
        download_videos = config.download_videos
        download_resolution = config.download_resolution
        use_residential_proxy = config.use_residential_proxy
        proxy_country = config.proxy_country
        force_refresh_cache = config.force_refresh_cache
        transcribe_videos = config.transcribe_videos

        api_token = os.environ.get("APIFY_API_KEY")
        if not api_token:
            return {
                "videos": [], "filtered_count": 0, "total_fetched": 0,
                "error": "未提供API令牌，请设置环境变量 APIFY_API_KEY"
            }

        # Get WhisperX URL from environment
        whisperx_base_url = None
        if transcribe_videos:
            whisperx_base_url = os.environ.get("WHISPERX_MODEL_URL")
            if not whisperx_base_url:
                logging.warning("Transcription requested, but WHISPERX_MODEL_URL environment variable is not set. Transcription will be skipped.")
                # Optionally return an error instead of skipping:
                # return {
                #     "videos": [], "filtered_count": 0, "total_fetched": 0,
                #     "error": "Transcription requested, but WHISPERX_MODEL_URL environment variable is not set."
                # }
                transcribe_videos = False # Disable transcription if URL is missing

        client = ApifyClient(api_token)
        store_id = None # Initialize store_id
        if download_videos:
            try:
                # Get store ID only if downloading
                store_id = self._get_or_create_store(client)
            except Exception as e:
                 return {
                    "videos": [], "filtered_count": 0, "total_fetched": 0,
                    "error": f"Failed to initialize download cache: {repr(e)}"
                }

        # --- Step 1: Fetch Channel Videos ---
        all_videos_data = []
        total_fetched = 0
        try:
            logging.info(f"Fetching up to {max_videos_per_channel} videos per channel from {len(channel_urls)} channels")
            channel_scraper_actor_id = "streamers/youtube-scraper"
            run_input_scrape = {
                "startUrls": [{"url": url} for url in channel_urls], # Use list comprehension
                "maxResults": max_videos_per_channel,  # Use the new input field
                "maxResultsShorts": 0,
                "maxResultStreams": 0,
                "sortVideosBy": "NEWEST"
            }
            # logging.info(f"Apify scrape input: {run_input_scrape}") # Debug log
            run_scrape = client.actor(channel_scraper_actor_id).call(run_input=run_input_scrape)
            all_videos_raw = list(client.dataset(run_scrape["defaultDatasetId"]).iterate_items())

            # Filter out member-only videos
            videos_data = [v for v in all_videos_raw if not v.get("isMembersOnly", False)]

            # Group videos by channel URL (if needed, or process as a flat list)
            # For simplicity, we'll process as a flat list first and sort later

            total_fetched = len(videos_data)
            logging.info(f"Fetched {total_fetched} videos initially across all channels.")

            # Apply time filter (applied after fetching all)
            filtered_videos = videos_data
            if time_filter > 0:
                current_time = datetime.now(timezone.utc)
                time_filtered_list = []
                for video in videos_data:
                    if "date" in video and video["date"]:
                        try:
                            video_date = datetime.fromisoformat(video["date"].replace('Z', '+00:00'))
                            if current_time - video_date < timedelta(hours=time_filter):
                                time_filtered_list.append(video)
                        except ValueError:
                             logging.warning(f"Could not parse date for video: {video.get('title', 'N/A')} ({video.get('url', 'N/A')})")
                    else:
                        logging.warning(f"Video missing date for time filtering: {video.get('title', 'N/A')} ({video.get('url', 'N/A')})")

                filtered_videos = time_filtered_list

            # Sort the final filtered list by date and limit if necessary (though Apify should handle per-channel limit)
            filtered_videos.sort(key=lambda x: x.get("date", ""), reverse=True)
            # Optional: apply a global limit if needed, though maxResultsPerChannel should suffice
            # filtered_videos = filtered_videos[:max_videos_per_channel * len(channel_urls)]

            filtered_count = len(filtered_videos)
            logging.info(f"Filtered down to {filtered_count} videos based on time ({time_filter} hours).")

        except Exception as e:
            logging.error(f"Error fetching channel videos: {repr(e)}")
            import traceback
            traceback.print_exc() # Add traceback for debugging
            return {
                "videos": [], "filtered_count": 0, "total_fetched": 0,
                "error": f"Error fetching channel videos: {repr(e)}"
            }

        # --- Step 2: Download Videos (if requested) ---
        if download_videos and filtered_videos:
            logging.info(f"Attempting to get download links for {filtered_count} videos (resolution: {download_resolution})")
            downloader_actor_id = "y1IMcEPawMQPafm02" # Actor for downloading

            for video in filtered_videos:
                video_url = video.get("url")
                if not video_url:
                    video["download_status"] = "error"
                    video["download_message"] = "Missing video URL"
                    video["download_url"] = None
                    video["download_cached"] = False
                    continue

                video["download_status"] = "pending" # Initial status
                cached_url = None
                is_cache_valid = False

                # 1. Check cache (if not forcing refresh)
                if not force_refresh_cache:
                    cached_url = self._get_link_from_store(client, store_id, video_url, download_resolution)
                    if cached_url:
                        logging.info(f"Cache hit for {video_url} ({download_resolution}). Checking validity...")
                        is_cache_valid = self._is_url_valid(cached_url)
                        if is_cache_valid:
                            logging.info(f"Cached URL is valid: {cached_url}")
                            video["download_status"] = "success"
                            video["download_message"] = "Successfully retrieved cached download link."
                            video["download_url"] = cached_url
                            video["download_cached"] = True
                            continue # Move to next video
                        else:
                            logging.info(f"Cached URL is invalid for {video_url}. Fetching fresh link.")

                # 2. Fetch fresh link (cache miss, invalid cache, or forced refresh)
                try:
                    logging.info(f"Fetching fresh download link for: {video_url} ({download_resolution})")
                    proxy_configuration = {"useApifyProxy": True}
                    if use_residential_proxy:
                        proxy_configuration["apifyProxyGroups"] = ["RESIDENTIAL"]
                        if proxy_country:
                            proxy_configuration["apifyProxyCountry"] = proxy_country

                    run_input_download = {
                        "startUrls": [video_url],
                        "quality": download_resolution,
                        "useFfmpeg": False,
                        "includeFailedVideos": False,
                        "proxy": proxy_configuration,
                    }

                    run_download = client.actor(downloader_actor_id).call(run_input=run_input_download)
                    download_results = list(client.dataset(run_download["defaultDatasetId"]).iterate_items())

                    if download_results and "downloadUrl" in download_results[0] and download_results[0]["downloadUrl"]:
                        download_url = download_results[0]["downloadUrl"]
                        video["download_status"] = "success"
                        video["download_message"] = "Successfully retrieved download link via Actor."
                        video["download_url"] = download_url
                        video["download_cached"] = False
                        # Save the fresh link to cache
                        self._save_link_to_store(client, store_id, video_url, download_url, download_resolution)

                        # --- >>> START TRANSCRIPTION BLOCK <<< ---
                        if transcribe_videos and whisperx_base_url:
                            logging.info(f"Starting transcription for: {video_url}")
                            transcription_status, transcription_result = self._get_transcription(download_url, whisperx_base_url)
                            video["transcription_status"] = transcription_status
                            if transcription_status == "success":
                                video["transcript"] = transcription_result
                                video["transcription_message"] = "Transcription successful."
                                logging.info(f"Transcription successful for {video_url}")
                            else:
                                video["transcript"] = None
                                video["transcription_message"] = transcription_result # Contains the error message
                                logging.error(f"Transcription failed for {video_url}: {transcription_result}")
                        else:
                            # Ensure keys exist even if transcription is skipped or failed before starting
                            video["transcription_status"] = "skipped"
                            video["transcript"] = None
                            if not transcribe_videos:
                                video["transcription_message"] = "Transcription was not requested."
                            elif not whisperx_base_url:
                                 video["transcription_message"] = "Transcription skipped: WHISPERX_MODEL_URL not set."
                            else: # Should not happen if download succeeded, but as fallback
                                 video["transcription_message"] = "Transcription skipped due to missing download URL."
                        # --- >>> END TRANSCRIPTION BLOCK <<< ---

                    else:
                        logging.warning(f"Could not find download link for {video_url} via Actor.")
                        video["download_status"] = "error"
                        video["download_message"] = "Could not find download link via Actor."
                        video["download_url"] = None
                        video["download_cached"] = False
                        # Ensure transcription keys exist even if download failed
                        video["transcription_status"] = "skipped"
                        video["transcript"] = None
                        video["transcription_message"] = "Skipped due to download failure."

                except Exception as e:
                    logging.error(f"Error fetching download link for {video_url}: {repr(e)}")
                    video["download_status"] = "error"
                    video["download_message"] = f"Error during download Actor call: {repr(e)}"
                    video["download_url"] = None
                    video["download_cached"] = False
                     # Ensure transcription keys exist even if download errored
                    video["transcription_status"] = "skipped"
                    video["transcript"] = None
                    video["transcription_message"] = "Skipped due to download error."

            # Add transcription info for cached videos as well
            for video in filtered_videos:
                if video.get("download_status") == "success" and video.get("download_cached") == True:
                    if transcribe_videos and whisperx_base_url and video.get("download_url"):
                         # Check if transcription was already done (e.g., in a previous run for this cached URL)
                         # This basic implementation will re-transcribe cached videos if requested.
                         # A more advanced cache could store transcription results too.
                        logging.info(f"Starting transcription for cached video: {video.get('url')}")
                        transcription_status, transcription_result = self._get_transcription(video["download_url"], whisperx_base_url)
                        video["transcription_status"] = transcription_status
                        if transcription_status == "success":
                            video["transcript"] = transcription_result
                            video["transcription_message"] = "Transcription successful (for cached video)."
                            logging.info(f"Transcription successful for cached {video.get('url')}")
                        else:
                            video["transcript"] = None
                            video["transcription_message"] = transcription_result # Contains the error message
                            logging.error(f"Transcription failed for cached {video.get('url')}: {transcription_result}")

                    elif "transcription_status" not in video: # Ensure keys exist if transcription wasn't run
                        video["transcription_status"] = "skipped"
                        video["transcript"] = None
                        if not transcribe_videos:
                             video["transcription_message"] = "Transcription was not requested."
                        elif not whisperx_base_url:
                            video["transcription_message"] = "Transcription skipped: WHISPERX_MODEL_URL not set."
                        else:
                             video["transcription_message"] = "Transcription skipped (cached video)."

        # --- Step 3: Return Results ---
        return {
            "videos": filtered_videos,
            "filtered_count": filtered_count,
            "total_fetched": total_fetched,
            "error": None # Indicate overall success if we reached here
        }


# --- Direct Test Code ---
if __name__ == "__main__":
    import os
    from easydict import EasyDict

    print("--- YouTube Channel Videos & Downloader Test ---")

    try:
        api_token = os.environ.get("APIFY_API_KEY", "")
        if not api_token:
            print("\nERROR: 请设置环境变量 APIFY_API_KEY")
            exit(1)
        else:
             print("\nAPIFY_API_KEY found.")


        # --- Test Case Configuration ---
        test_config = EasyDict({
            "channel_urls": [
                "https://www.youtube.com/@yttalkjun",
                "https://www.youtube.com/@shanghaojin" # Add another channel
            ],
            "max_videos_per_channel": 1, # Get latest 1 video per channel
            "time_filter": 0,
            "download_videos": True,  # Ensure downloading is enabled for transcription
            "download_resolution": "360",
            "use_residential_proxy": False, # Set to True if needed
            "proxy_country": "US",
            "force_refresh_cache": False,   # Set to True to ignore cache
            "transcribe_videos": True,     # <<< ENABLE TRANSCRIPTION FOR TEST >>>
        })

        print("\nRunning test with config:")
        print(f"  Channel URLs: {test_config.channel_urls}")
        print(f"  Max Videos per Channel: {test_config.max_videos_per_channel}")
        print(f"  Time Filter (hours): {test_config.time_filter}")
        print(f"  Download Videos: {test_config.download_videos}")
        if test_config.download_videos:
             print(f"  Download Resolution: {test_config.download_resolution}")
             print(f"  Use Residential Proxy: {test_config.use_residential_proxy}")
             print(f"  Proxy Country: {test_config.proxy_country}")
             print(f"  Force Refresh Cache: {test_config.force_refresh_cache}")
             print(f"  Transcribe Videos: {test_config.transcribe_videos}")


        # Create widget instance and execute
        widget = YouTubeChannelVideos()
        print("\nExecuting widget...")
        result = widget.execute({}, test_config) # Pass empty environ and config

        # --- Output Results ---
        print("\n--- Execution Result ---")
        if result.get("error"):
            print(f"Error: {result['error']}")
        else:
            print(f"Total videos fetched initially: {result['total_fetched']}")
            print(f"Videos after time filter: {result['filtered_count']}")

            if result['videos']:
                print("\n--- Video Details ---")
                for i, video in enumerate(result['videos']):
                    print(f"\nVideo #{i+1}:")
                    print(f"  Title: {video.get('title', 'N/A')}")
                    print(f"  URL: {video.get('url', 'N/A')}")
                    print(f"  Uploaded: {video.get('date', 'N/A')}")
                    print(f"  Views: {video.get('viewCount', 'N/A')}")
                    print(f"  Duration: {video.get('duration', 'N/A')}")
                    # Display download info if available
                    if 'download_status' in video:
                        print(f"  Download Status: {video['download_status']}")
                        print(f"  Download Message: {video['download_message']}")
                        print(f"  Download URL: {video.get('download_url', 'N/A')}")
                        print(f"  Download Cached: {video.get('download_cached', 'N/A')}")
                    if 'transcription_status' in video:
                        print(f"  Transcription Status: {video['transcription_status']}")
                        print(f"  Transcription Message: {video['transcription_message']}")
                        # Optionally print only a snippet of the transcript if it's long
                        transcript_preview = str(video.get('transcript', 'N/A'))
                        if len(transcript_preview) > 100:
                            transcript_preview = transcript_preview[:100] + "..."
                        print(f"  Transcript: {transcript_preview}")
            else:
                print("\nNo videos found matching the criteria.")

    except Exception as e:
        import traceback
        print(f"\n--- Test Script Failed ---")
        print(f"Error: {repr(e)}")
        # traceback.print_exc() # Uncomment for detailed stack trace

    print("\n--- Test Finished ---")
    # print("\nReminder: Ensure necessary dependencies are installed (apify-client, requests, pydantic, easydict).")