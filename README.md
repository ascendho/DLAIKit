> [English version](README.en.md) is also available.

# DeepLearning.AI 课程导出器

![Python](https://img.shields.io/badge/python-%3E%3D3.9-blue)
![Playwright](https://img.shields.io/badge/browser-Playwright-2EAD33)
![Tests](https://img.shields.io/badge/tests-pytest-blueviolet)
![Output](https://img.shields.io/badge/output-Markdown%20%2B%20JSON-lightgrey)
![Config](https://img.shields.io/badge/config-JSON-informational)
![License](https://img.shields.io/badge/license-MIT-green)

将 DeepLearning.AI 课程字幕、课程元数据、资源列表和可选 lab 代码导出到本地文件。
工具使用 Playwright 抓取页面，可以处理动态渲染的课程页和需要登录的 lesson。

## 功能

- 从课程主页自动发现 lesson 列表。
- 为每个有字幕的 lesson 保存 Markdown。
- 自动生成完整学习包：`index.md`、`course-overview.md`、`resources.md`、`manifest.json`。
- 根据配置中的 Jupyter/Lab 链接递归下载课程代码。
- 自动从课程 code lesson 的 Jupyter iframe 读取临时 token，通常不需要手动找 token。
- 复用 `.auth/deeplearning_ai.json` 中保存的本地 Playwright 登录态。

## 安装

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"
python3 -m playwright install chromium
```

## 配置

在项目根目录编辑 `dlai-transcripts.json`：

```json
{
  "course_url": "https://www.deeplearning.ai/courses/building-coding-agents-with-tool-execution",
  "code_url": "https://...lab-aws-production.deeplearning.ai/tree",
  "output_dir": "exports",
  "auth_state": ".auth/deeplearning_ai.json",
  "browser_visibility": "auto",
  "force": false
}
```

`course_url` 是必填项。`code_url` 可以留空；留空时只导出字幕和学习包元数据，不下载
lab 代码。

## 运行

```sh
dlai-transcripts
```

程序会始终按完整学习包方式导出所有可见资源，不需要额外参数。首次需要登录时，命令可能会打开一个浏览器窗口。你在浏览器里完成登录后，程序会自动继续运行。之后再次运行会复用保存的登录态，并默认在后台运行。

## 导出结构

默认导出到项目根目录下的 `exports/`：

```text
exports/<course-slug>/
  index.md
  transcripts/
    01-<lesson-slug>.md
  code/
  course-overview.md
  resources.md
  manifest.json
```

- `index.md`：lesson 索引、抓取状态和代码下载摘要。
- `transcripts/`：逐课字幕 Markdown。
- `code/`：从 Jupyter/Lab 链接下载的课程代码和资料。
- `course-overview.md`：课程摘要、学习目标、讲师、lesson 类型和时长。
- `resources.md`：代码示例、测验或作业页面，以及页面中可见的资源链接。
- `manifest.json`：结构化课程、lesson、资源和抓取结果数据。

`metadata` 表示该课程项没有生成单独的字幕 Markdown 文件，只记录在 `index.md` 和
`manifest.json` 中。代码示例、测验或作业页面如果没有可见字幕，会标记为
`metadata`，而不是 `failed`。

## 登录态

工具不会保存用户名或密码，只保存复用网页登录所需的本地 Playwright 浏览器状态：

```text
.auth/deeplearning_ai.json
```

正常情况下，工具会从课程 code lesson 的 iframe 里自动读取临时 token。只有课程页面没有暴露 iframe token 时，才需要在项目根目录的 `dlai-transcripts.json` 中添加 `"code_token": "你的 Jupyter token"`，或把 `"browser_visibility"` 改为 `"visible"` 后重新运行一次。

## 说明

- 本项目面向个人学习工作流。
- 源码位于 `src/study/`，这是标准 Python `src` layout 下的包目录，不是生成输出目录。
- DeepLearning.AI 页面结构可能变化；解析器测试使用本地 HTML fixture 来保持核心行为稳定。
