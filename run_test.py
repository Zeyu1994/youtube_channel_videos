"""
从ShellAgent根目录运行的测试脚本。
使用方法: python custom_widgets/youtube_channel_videos/run_test.py
"""

from easydict import EasyDict
import os
import sys

# 添加当前工作目录到sys.path
sys.path.append(os.getcwd())

try:
    from custom_widgets.youtube_channel_videos.youtube_channel_videos import YouTubeChannelVideos
    
    # 从环境变量获取API令牌
    api_token = os.environ.get("APIFY_API_KEY")
    
    if not api_token:
        print("错误: 未设置环境变量APIFY_API_KEY")
        print("请设置环境变量后再运行测试:")
        print("# Windows PowerShell: $env:APIFY_API_KEY='您的API令牌'")
        print("# Linux/Mac: export APIFY_API_KEY='您的API令牌'")
        sys.exit(1)
    
    # 创建widget实例
    widget = YouTubeChannelVideos()
    
    # 测试用例1：基本测试
    print("测试用例1：基本测试")
    config = EasyDict({
        "channel_url": "https://www.youtube.com/@yttalkjun",
        "max_videos": 3,
        "time_filter": 24
    })
    
    print("输入配置:")
    for key, value in config.items():
        print(f"  {key}: {value}")
    
    try:
        output = widget({}, config)
        print("\n输出结果:")
        print(f"  获取的视频总数: {output['total_fetched']}")
        print(f"  时间过滤后的视频数量: {output['filtered_count']}")
        
        if output['filtered_count'] > 0:
            print("\n视频详情:")
            for i, video in enumerate(output['videos']):
                print(f"\n视频 #{i+1}:")
                print(f"  标题: {video.get('title', 'N/A')}")
                print(f"  URL: {video.get('url', 'N/A')}")
                print(f"  上传时间: {video.get('date', 'N/A')}")
                print(f"  观看次数: {video.get('viewCount', 'N/A')}")
                print(f"  时长: {video.get('duration', 'N/A')}")
                print(f"  会员专属: {video.get('isMembersOnly', False)}")
        else:
            print("\n未找到符合条件的视频")
            if 'error' in output:
                print(f"错误: {output['error']}")
    except Exception as e:
        print(f"测试失败: {str(e)}")
    
    # 测试用例2：不同时间过滤器
    print("\n\n测试用例2：不同时间过滤器")
    config.time_filter = 1  # 只获取1小时内的视频
    
    print("输入配置:")
    for key, value in config.items():
        print(f"  {key}: {value}")
    
    try:
        output = widget({}, config)
        print("\n输出结果:")
        print(f"  获取的视频总数: {output['total_fetched']}")
        print(f"  时间过滤后的视频数量: {output['filtered_count']}")
        if 'error' in output:
            print(f"错误: {output['error']}")
    except Exception as e:
        print(f"测试失败: {str(e)}")

except ImportError as e:
    print(f"导入错误: {str(e)}")
    print("请确保您已安装所需依赖：")
    print("  pip install -r custom_widgets/youtube_channel_videos/requirements.txt")
    print("  pip install easydict")
    
print("\n注意：请确保在ShellAgent根目录运行此测试。")
print("运行命令: python custom_widgets/youtube_channel_videos/run_test.py")
print("您必须设置环境变量APIFY_API_KEY来提供API令牌") 