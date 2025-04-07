from pydantic import Field
from typing import List, Dict, Any
from datetime import datetime, timezone, timedelta
from apify_client import ApifyClient
import os

from proconfig.widgets.base import WIDGETS, BaseWidget

@WIDGETS.register_module()
class YouTubeChannelVideos(BaseWidget):
    CATEGORY = "Custom Widgets/YouTube"
    NAME = "YouTube Channel Videos"
    
    class InputsSchema(BaseWidget.InputsSchema):
        channel_url: str = Field(..., description="YouTube频道URL，例如: https://www.youtube.com/@channelname")
        max_videos: int = Field(1, description="要获取的最新视频数量 (1-10)", ge=1, le=10)
        time_filter: int = Field(24, description="只返回多少小时内上传的视频 (0表示不过滤)", ge=0)
    
    class OutputsSchema(BaseWidget.OutputsSchema):
        videos: List = Field([], description="符合条件的视频列表")
        filtered_count: int = Field(0, description="时间过滤后的视频数量")
        total_fetched: int = Field(0, description="获取的视频总数")
    
    def execute(self, environ, config):
        # 使用config.xxx而不是config['xxx']
        channel_url = config.channel_url
        max_videos = config.max_videos
        time_filter = config.time_filter
        
        # 从环境变量获取API密钥
        api_token = os.environ.get("APIFY_API_KEY")
        
        if not api_token:
            return {
                "videos": [],
                "filtered_count": 0,
                "total_fetched": 0,
                "error": "未提供API令牌，请设置环境变量APIFY_API_KEY"
            }
        
        # 初始化Apify客户端
        client = ApifyClient(api_token)
        
        # 准备Actor输入
        run_input = {
            "startUrls": [
                {
                    "url": channel_url
                }
            ],
            "maxResults": max_videos * 2,  # 获取更多视频以便在过滤后仍有足够数量
            "maxResultsShorts": 0,
            "maxResultStreams": 0,
            "sortVideosBy": "NEWEST"
        }
        
        # 运行Actor并等待完成
        try:
            run = client.actor("streamers/youtube-scraper").call(run_input=run_input)
            
            # 获取结果
            all_videos = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            
            # 移除会员专属视频 (isMembersOnly: true)
            videos = [v for v in all_videos if not v.get("isMembersOnly", False)]
            
            # 按上传时间从新到旧排序
            videos.sort(key=lambda x: x.get("date", ""), reverse=True)
            
            # 限制数量
            videos = videos[:max_videos]
            
            # 应用时间过滤器（如果设置）
            filtered_videos = videos
            if time_filter > 0:
                current_time = datetime.now(timezone.utc)
                filtered_videos = []
                
                for video in videos:
                    if "date" in video:
                        video_date_str = video["date"]
                        video_date = datetime.fromisoformat(video_date_str.replace('Z', '+00:00'))
                        time_difference = current_time - video_date
                        
                        if time_difference < timedelta(hours=time_filter):
                            filtered_videos.append(video)
            
            return {
                "videos": filtered_videos,
                "filtered_count": len(filtered_videos),
                "total_fetched": len(videos)
            }
            
        except Exception as e:
            return {
                "videos": [],
                "filtered_count": 0,
                "total_fetched": 0,
                "error": str(e)
            }


# 直接测试代码
if __name__ == "__main__":
    import os
    
    try:
        # 从环境变量获取API令牌
        api_token = os.environ.get("APIFY_API_KEY", "")
        
        if not api_token:
            print("请设置环境变量APIFY_API_KEY")
            # 如果环境变量未设置，提示设置
            print("您必须设置环境变量APIFY_API_KEY才能运行此组件")
            exit(1)
        
        # 创建配置
        from easydict import EasyDict
        config = EasyDict({
            "channel_url": "https://www.youtube.com/@yttalkjun",
            "max_videos": 2,
            "time_filter": 24
        })
        
        # 创建widget实例并执行
        widget = YouTubeChannelVideos()
        
        print("正在获取YouTube频道视频...")
        print(f"频道: {config.channel_url}")
        print(f"最大视频数: {config.max_videos}")
        print(f"时间过滤: {config.time_filter}小时")
        
        result = widget({}, config)
        
        # 输出结果
        print("\n结果:")
        print(f"获取的视频总数: {result['total_fetched']}")
        print(f"时间过滤后的视频数量: {result['filtered_count']}")
        
        # 显示视频信息
        if result['videos']:
            print("\n视频信息:")
            for i, video in enumerate(result['videos']):
                print(f"\n视频 #{i+1}:")
                print(f"  标题: {video.get('title', 'N/A')}")
                print(f"  URL: {video.get('url', 'N/A')}")
                print(f"  上传时间: {video.get('date', 'N/A')}")
                print(f"  观看次数: {video.get('viewCount', 'N/A')}")
                print(f"  时长: {video.get('duration', 'N/A')}")
                print(f"  会员专属: {video.get('isMembersOnly', False)}")
        else:
            print("\n未找到符合条件的视频")
            if 'error' in result:
                print(f"错误: {result['error']}")
    
    except Exception as e:
        print(f"测试失败: {e}")
        
    print("\n注意: 请确保已安装所需依赖:")
    print("pip install -r custom_widgets/youtube_channel_videos/requirements.txt") 