# 发布说明（给仓库所有者）

这份文件列出对外发布前**只能由你本人做**的事：arXiv 投稿、Hugging Face 上传、社区帖子。仓库里已经备好了能备的东西：

- `paper/build.sh`：把 PAPER.md 转成 LaTeX 并编译成 PDF；
- `hf/`：Hugging Face 模型页内容和上传脚本。

标"未核实"的平台规则没有查证过，请以平台当时的页面为准。

## 1. arXiv 排版稿

**构建。**

```sh
PANDOC=<pandoc 路径> TECTONIC=<tectonic 路径> paper/build.sh <输出目录>   # 默认输出 ./out/paper（不进 git）
```

- 产物：`pixeltree.tex`、`refs.bib`、`pixeltree.bbl`、`pixeltree.pdf`。
- 构建后会自动运行 `paper/check.py`，检查三件事：页数；没有内容伸出页边（overfull hbox）；PAPER.md 里的每个数字都出现在 PDF 里。
- PAPER.md 更新后（例如 R5 一节的数字）重跑一次即可，不手改 .tex。

**作者署名与单位。**
- 默认作者是 Xinghan Xu（对外署名；GitHub 账号名只出现在仓库 URL 里）。
- 加单位或改署名：`PAPER_AUTHOR="Xinghan Xu（单位）" paper/build.sh`。
- 单位、通讯邮箱、致谢都由你决定，脚本不替你填。

**排版引擎。**
- 本机用 XeLaTeX（tectonic）编译，模板里另有一条 pdfLaTeX 分支（CJKutf8 处理正文里引用的两个 OCR 汉字"业""目"）。**pdfLaTeX 分支没有在本机编译过。**
- arXiv 默认用 pdfLaTeX 编译源文件；是否支持 XeLaTeX：未核实。
- 建议投稿前在 Overleaf 上用 pdfLaTeX 编译一次，确认能过：上传 `pixeltree.tex`、`refs.bib`，菜单 → Compiler 选 pdfLaTeX。
- 上传 arXiv 时把 `pixeltree.bbl` 一起放进去。arXiv 是否会自己跑 BibTeX：未核实；带上 .bbl 最稳。

**Overleaf 编译（不想装工具时）。**
- 上传 `pixeltree.tex` 与 `refs.bib`，Compiler 选 XeLaTeX 或 pdfLaTeX。
- XeLaTeX 下会找 Noto Serif CJK SC 或 FandolSong 显示汉字、找 DejaVu Sans Mono 显示"√"。找不到时有退路（不显示汉字字形 / 用数学符号）。Overleaf 上有哪些字体：未核实。

**你需要自己做的事。**
1. **账号。** 注册 arXiv 账号，填写真实姓名与单位。
2. **类目。** 建议主类 cs.HC（人机交互），交叉列 cs.AI、cs.CV。理由：
   - 论文主题是 GUI agent 怎样"看"界面；
   - 结果包括检测器（CV）和 agent 实验（AI）。

   cs.CL 也可以考虑（文本模型读树）。最终由你决定。
3. **背书（endorsement）。** 首次在某个类目投稿的作者可能需要一位已有该类目投稿记录的人背书。你是否需要、找谁：未核实（提交流程里会提示）。
4. **许可证。**
   - arXiv 提交时要选论文本身的分发许可。常见选项有 arXiv 非独占分发许可和几种 CC 许可，例如 CC BY 4.0；具体列表以提交页为准，未核实。
   - 这只管论文 PDF / 源文件。代码与权重仍是 AGPL-3.0。
5. **署名与相关工作。**
   - `refs.bib` 里六篇的合作者写成 "others"，投稿前从 arXiv 摘要页补全作者列表。
   - 标题与编号已逐条核对过。
6. **公开顺序。**
   - 论文里的链接都指向 GitHub 仓库；仓库还是 private 时，读者点进去是 404。
   - 建议先把 GitHub 仓库改为 public，再投 arXiv。
7. **提交记录里的身份。** git 提交记录显示的提交者名字 / 邮箱是本机 git 配置，与署名 Xinghan Xu 不同。是否改写由你决定；仓库公开前可以改写（公开后改写会影响已有克隆）。
8. **日期相关的事实。**
   - 论文写明日历任务假定在 2026-11-08 到 2026-11-14 那一周运行。
   - PAPER.md 以后再改数字时，先改 PAPER.md 与 results/，再重建 PDF，并同步改下面帖子里的数字。

## 2. Hugging Face 模型页

`hf/` 目录就是模型仓库的内容：
- `hf/README.md`：带 YAML 头的模型卡。`{{REPO_ID}}` 由上传脚本自动替换。
- `hf/upload.py`：上传脚本。
- 权重不进 git，由脚本从本地取。

```sh
pip install -e ".[hf]"                                  # huggingface_hub
hf auth login                                           # 浏览器或 token 登录；token 需要 write 权限；只存在 HF 自己的缓存里
python weights/download.py                              # 或在仓库 private 期间：gh release download v0.1.0 -R <owner>/pixeltree -p pixeltree-detector-v1.pt -D ~/.cache/pixeltree
python hf/upload.py <你的HF用户名>/pixeltree-detector --dry-run    # 只核对 sha256、列文件，不联网
python hf/upload.py <你的HF用户名>/pixeltree-detector              # 新建为 private，并上传 README.md、权重、SHA256SUMS、LICENSE
```

- **默认 private。** `--public` 只对**新建**仓库有效；已存在的仓库不改可见性。
- **核对。** 上传后在 Hugging Face 网页上检查模型卡渲染、文件列表、许可证标签。
- **公开。** 确认无误后，在网页的 Settings 里改为 public。命令行能否改可见性、用什么命令：未核实。
- **顺序。** 模型卡里的链接同样指向 GitHub 仓库，建议 GitHub 先公开。
- **token。** 不要把 token 写进任何文件或命令历史；`hf auth login` 会把它存在 Hugging Face 自己的缓存里。

## 3. 社区帖子草稿

三版都只用 PAPER.md 里已有的发现（R5 已按 48 个任务的结果写）。各社区的发帖规则（自我推广比例、标题格式、是否允许 private 链接）：未核实，请发帖前读一遍版规。

### 3.1 Show HN（英文）

**Title:** Show HN: pixeltree – a 19 MB screenshot-to-element-tree model, and which GUI agents actually need it

**What it is.** We distilled "look at the screen" into a small local detector. Claude Opus labelled 2,782 screenshots under one written box convention; we fine-tuned YOLO11s on them, and with OCR it turns any screenshot into a text list of UI elements (role, name, box). F1 0.854 on 10 Linux apps it never saw in training.

**What we found** (48 programmatically graded tasks in 8 unseen Linux apps):
- **Claude doesn't need the tree.** Claude Haiku does best with the screenshot alone. Reading only our tree is 25 points worse (95 % interval −38 to −12), and adding the tree to the screenshot gains nothing.
- **GLM 5.3 Flash gains from it.** Screenshot + tree is +15 points over the screenshot alone (interval 2 to 27).
- **A text-only model can use the desktop through it.** LongCat 2.0 cannot see images and completed 33/48 tasks reading our tree. On the two GTK4 apps whose accessibility tree is empty, ours was the only thing that worked; elsewhere the system tree did as well or better.
- **A cheap fix for screenshot agents.** Drop the redundant `observe` tool and send the first screenshot with the task: 89 % vs 82 %, with fewer steps and lower cost.
- **Our own mistake.** A token-saving cleanup rule deleted the close button's "×", and agents closed the app in 39 of 144 episodes. The tree's other gaps: unnamed or garbled icon names, no control state, duplicate rows.

**What's in the repo.** Code, weights (AGPL-3.0), the testbench, a replay viewer with example episodes, the labelling recipe and every result table. It's a research prototype, released so someone can take it further — especially icon meaning and control state. <GitHub link>

### 3.2 r/LocalLLaMA（英文）

**Title:** A 19 MB local screenshot-to-element-list model: Claude didn't need it, a text-only model could drive a desktop with it

**What it is.** A YOLO11s detector (fine-tuned on 2,782 Claude-Opus-labelled screenshots) plus OCR. It outputs one line per UI element: `role [id] "name" @(x,y,w,h)`. Detector-only speed: 44 ms per frame on an RTX 2060, 260 ms on a laptop CPU. F1 0.854 on 10 unseen Linux apps.

**What we found** (48 graded tasks in 8 Linux apps; each model compared only with itself):
- **Claude Haiku:** the screenshot is enough. Tree only is −25 points (−38 to −12); screenshot + tree ties the screenshot.
- **GLM 5.3 Flash:** screenshot + tree is +15 points over the screenshot only (2 to 27).
- **LongCat 2.0, which cannot take images:** 33/48 with our tree. It was the only usable input on the two apps whose accessibility tree is empty; on the other six apps the system accessibility tree was ahead.
- **Side finding:** removing the redundant `observe` call made the screenshot agent better and cheaper (89 % vs 82 %).
- **Our own bug:** a cleanup rule blanked the "×" close button and agents closed the app. Other gaps: unnamed or garbled icons, no checkbox / toggle state, duplicate rows.

**What's there / what's missing.** Weights, code, testbench, replay viewer, result tables (AGPL-3.0). We have **not** tested a small local model as the reader — that's the obvious next experiment if you run local VLMs or text models. <GitHub link>

### 3.3 中文版（例如即刻 / V2EX / 知乎，平台自选）

**标题：** pixeltree：把"看屏幕"蒸馏成 19 MB 的本地小模型——以及哪些 AI 真的需要它

**是什么。** 用 Claude Opus 按一份书面画框规范标了 2,782 张截图，微调 YOLO11s，再配上 OCR，把任意截图变成一份元素清单（角色、名字、位置）。在训练时没见过的 10 个 Linux 应用上，找元素的 F1 是 0.854。

**发现了什么**（8 个没见过的 Linux 应用、48 个由程序判分的任务）：
- **Claude 不需要树。** Claude Haiku 只看截图最好；只读我们的树低 25 个百分点（95 % 区间 −38 到 −12），截图加树也没有提升。
- **GLM 5.3 Flash 加上树更好。** 截图 + 树比只看截图高 15 个百分点（区间 2 到 27）。
- **看不了图的模型靠树能用桌面。** LongCat 2.0 读我们的树做成 33/48。在系统无障碍树为空的两个 GTK4 应用上，我们的树是唯一可用的输入；其余应用系统树一样好或更好。
- **去掉多余的 observe。** 截图 agent 反而更好也更省：89 % 对 82 %，步数和花费都更少。
- **我们自己的错。** 一条省 token 的清洗规则把关闭按钮的 "×" 清掉了，144 个回合里有 39 个 agent 直接关掉了应用。树的其它缺口：图标没有名字或被 OCR 成乱码、控件没有状态、同一元素重复出现。

**仓库里有什么。** 代码、权重（AGPL-3.0）、测试台、带示例回合的回放查看器、标注配方和全部结果表。这是研究原型，放出来是希望有能力的团队接着做，尤其是图标含义和控件状态这两块。<GitHub 链接>
