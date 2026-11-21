# AI4S 科研信息工作台

这是集成电路科研信息工作台的完整源码。已有公开页面位于 [GitHub Pages](https://beesoven-star.github.io/ai4s-demo/)。本地运行可使用采集、资料整理、技术专题和模型设置。

- **热点与技术观察**提供本周简报、今日观察、技术跟踪和双榜单。热点关注度榜按独立媒体覆盖统计，提供近 7 天和近 30 天窗口。近 30 天榜单最多显示前 50 条。
- **技术专题与评价**汇集进展、原始资料和评价，按证据情况生成定性结论或评分。
- **每日发现**支持新闻及文献的采集、筛选、详情阅读，以及收藏和阅读记录。

## 在本地运行

使用 Python 3.12 或更新版本和 Node.js 22。在仓库根目录执行以下步骤。

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd --prefix web ci
npm.cmd --prefix web run build
.\.venv\Scripts\python.exe .\scripts\ic_preview_server.py
```

### macOS 或 Linux

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm --prefix web ci
npm --prefix web run build
.venv/bin/python scripts/ic_preview_server.py
```

打开 [本地工作台](http://127.0.0.1:8001/)。首次启动会创建自己的资料库。可在「每日发现」的「采集管理」查看来源、调整时间或手动采集。需要自动整理简报、新闻和论文要点、技术专题及评价时，在「设置」中配置自己的模型 API。

本地服务运行期间，默认每天北京时间 08:00 采集新闻和论文，新闻约每三小时补查一次。关闭服务会停止本地定时任务。库文件、密钥、收藏和工作文档由各使用者在本地保存。

## 代码与说明

- `src/` 包含后端、采集和整理任务。
- `web/` 包含前端与公开展示样本。使用 `npm --prefix web run build:pages` 构建静态展示。
- `resources/` 包含公开来源配置、专题目录和展示所需的固定资料。
- [集成电路自动观察流程](docs/ic-observation-workflow.md)说明采集、发布、跟踪和评价逻辑。
- [技术观察记录](docs/ic-technology-briefing.md)保存首版选材和评价口径。

项目沿用 [MIT 许可证](LICENSE)。

