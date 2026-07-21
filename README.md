<div align="center">
  <a href="https://nonebot.dev/store/plugins">
    <img src="./docs/NoneBotPlugin.svg" width="300" alt="logo">
  </a>
</div>
<div align="center">

# nonebot_plugin_ai_group

</div>

## 📖 介绍

基于 NoneBot2，使用 AI 分析群聊记录。支持在群聊中按消息条数总结，或私聊机器人总结指定群在某段时间内的消息。

## 💿 安装

使用nb-cli安装插件

```shell
nb plugin install nonebot_plugin_ai_group
```

使用pip安装插件

```shell
pip install nonebot_plugin_ai_group
```

## ⚙️ 配置

### AI 账户配置项

每个账户（Gemini/OpenAI）都支持以下基础配置，至少填写一个账户，填多个时，当默认API错误时可根据优先级依次降级处理：

- `name`: 账户的唯一名称（必填）
- `api_key`: 该账户的 API Key（必填）
- `model`: 该账户要使用的模型名称（必填）
- `proxy`: 为该账户单独设置代理
- `timeout`: 该账户的 API 请求超时时间(秒)，默认 60

#### OpenAI 兼容格式特定配置

- `provider`: 固定为 "openai"（必填）
- `base_url`: OpenAI API 兼容格式的访问地址（必填）

#### Gemini 特定配置

- `provider`: 固定为 "gemini"（必填）

#### AI 账户配置示例

```env
# Gemini 配置
ai_group_accounts__0__provider="gemini"
ai_group_accounts__0__name="gemini-1"
ai_group_accounts__0__api_key="your_gemini_api_key"
ai_group_accounts__0__model="gemini-2.5-flash"

# OpenAI 配置
ai_group_accounts__1__provider="openai"
ai_group_accounts__1__name="deepseek-1"
ai_group_accounts__1__base_url="https://api.deepseek.com"
ai_group_accounts__1__api_key="your_openai_api_key"
ai_group_accounts__1__model="deepseek-chat"

# 根据需要可添加更多账户配置
# ai_group_accounts__2__...
```

### 功能配置项

如无特殊需求，使用默认配置即可：

|          配置项          | 类型  | 默认值 |                           说明                           |
| :----------------------: | :---: | :----: | :------------------------------------------------------: |
| ai_group_default_account |  str  |  None  | 默认使用的账户名称；未设置时使用列表中的第一个账户       |
|  ai_group_max_messages   |  int  |  1000  |                  单次总结允许读取的最大消息数            |
|  ai_group_min_messages   |  int  |   50   |                  单次总结允许读取的最小消息数            |
|    ai_group_cooldown     |  int  |   0    |                  单个用户调用冷却时间(秒)                |
| ai_group_render_image    | bool  |  True  |                  是否将总结渲染为图片发送                |
| ai_group_require_command_prefix | bool | True | 是否仅匹配带 NoneBot 命令前缀的命令；关闭时两种都匹配 |
|   ai_group_queue_size    |  int  |   10   |                  等待处理的任务队列容量                  |
| ai_group_request_timeout |  int  |  300   |                  任务入队及处理总超时(秒)                |
|    ai_group_workers      |  int  |   2    |                  同时处理任务的最大并发数                |

## 🕹️ 使用

`ai_group_require_command_prefix` 默认开启。开启时只响应 `/总结` 等带前缀命令；设为 `false` 时，同时响应 `/总结` 和 `总结`。

**/总结 [消息数量] [特定内容?]** ：生成该群最近消息数量的总结或指定内容的总结，特定内容为可选项。

**私聊机器人：/总结 [群号] [时间段]** ：总结指定群在最近一段时间内的消息，并将结果私聊返回。时间段支持 `m`（分钟）、`h`（小时）、`d`（天）以及小数，例如：

```text
/总结 855634423 10m
/总结 855634423 1.5h
/总结 855634423 1d
```

私聊调用者必须是目标群成员，且机器人必须能够读取该群。单次最多读取 `ai_group_max_messages` 条消息；达到上限时，回复中会提示可能存在未包含的更早消息。

**/总结定时 [时间] [最少消息数量?=ai_group_max_messages]** ：每天在指定时间检查最近 24 小时的群消息；达到最少消息数量时生成总结。时间：0~23，最少消息数量默认为单次总结最大消息数，每群独立计算，默认不启用。

**/总结定时取消** ：取消本群的定时内容总结。

## 🙏 感谢

[github-markdown-css](https://github.com/sindresorhus/github-markdown-css) - 用于美化Markdown文档
