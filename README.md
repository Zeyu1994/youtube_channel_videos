# YouTube频道视频获取组件

这个自定义组件允许用户获取指定YouTube频道的最新视频，并可以按时间过滤结果。

## 功能特点

- 获取指定YouTube频道的最新视频
- 支持设置要获取的视频数量（1-10个）
- 时间过滤器：只返回指定时间范围内上传的视频
- 自动过滤会员专属视频（isMembersOnly: true）
- 返回的视频按上传时间从新到旧排序
- 返回视频的详细信息

## 依赖

此组件使用Apify API来抓取YouTube频道数据，您需要：

1. 在[Apify](https://apify.com/)注册一个账号
2. 获取您的API令牌（API Token）
3. 设置环境变量`APIFY_API_KEY`为您的API令牌

## 安装

安装所需依赖：

```bash
pip install -r custom_widgets/youtube_channel_videos/requirements.txt
```

## 环境变量设置

此组件必须设置以下环境变量才能运行：

```bash
# Windows PowerShell
$env:APIFY_API_KEY="你的Apify API令牌"

# Linux/Mac
export APIFY_API_KEY="你的Apify API令牌"
```

## 使用方法

组件输入参数:

- `channel_url` (字符串): YouTube频道URL，例如: https://www.youtube.com/@channelname
- `max_videos` (整数): 要获取的最新视频数量 (1-10)，默认为1
- `time_filter` (整数): 只返回多少小时内上传的视频，设为0表示不过滤，默认为24小时

环境变量:
- `APIFY_API_KEY`: 您的Apify API令牌（必需）

组件输出:

- `videos`: 符合条件的视频列表，每个视频包含详细信息如标题、URL、上传时间等
- `filtered_count`: 时间过滤后的视频数量
- `total_fetched`: 获取的视频总数（已排除会员专属视频）

## 示例

在ShellAgent的ProConfig界面中：

1. 首先，确保已设置环境变量`APIFY_API_KEY`
2. 添加"YouTube Channel Videos"节点
3. 设置频道URL
4. 可选：调整`max_videos`和`time_filter`参数
5. 运行工作流程

## 测试

有三种方式可以测试此组件：

### 方法1：直接运行主模块

```bash
# 设置API令牌环境变量（必需）
# Windows: $env:APIFY_API_KEY="你的API令牌"
# Linux/Mac: export APIFY_API_KEY="你的API令牌"

# 在ShellAgent根目录执行
python custom_widgets/youtube_channel_videos/youtube_channel_videos.py
```

### 方法2：使用测试脚本

```bash
# 设置API令牌环境变量（必需）
# Windows: $env:APIFY_API_KEY="你的API令牌"
# Linux/Mac: export APIFY_API_KEY="你的API令牌"

# 在ShellAgent根目录执行
python custom_widgets/youtube_channel_videos/run_test.py
```

注意：测试前请确保已安装所需依赖：
```bash
pip install -r custom_widgets/youtube_channel_videos/requirements.txt
pip install easydict
``` 