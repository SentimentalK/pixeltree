# pixeltree：把“看屏幕”蒸馏进小型本地模型——哪些有效，哪些无效

*简短技术报告。状态：研究原型。英文版：[PAPER.md](PAPER.md)（以英文版为准）。*

**摘要。** 我们在 2,782 张桌面和网页截图上训练了一个小型目标检测器（YOLO11s，19 MB）。这些截图由前沿模型（Claude Opus）依照一份书面的框选约定进行标注。检测器与 OCR 结合后，可以把任意截图转换为屏幕元素的文本列表（“树”，即元素树）。在训练中从未出现过的 10 个 Linux 应用上，它在相同的标注约定下取得类无关 F1 0.854。随后我们搭建了一个测试平台，包含 8 个未见过的 Linux 桌面应用中的 48 个任务，任务由程序自动评分。我们借此检验：智能体读取我们的树、读取系统无障碍树，还是只读取普通截图，哪种效果更好。答案取决于读取者。Claude 类智能体（Claude Haiku）只用截图时表现最好（86 %），加入我们的树后毫无收益。两个能看图像的非 Claude 模型（GLM 5.3 Flash、DeepSeek V4.1 Flash）在一项规模较小的实验中，有树时比没有树时表现更好。一个纯文本模型（LongCat 2.0）只有通过树才能操作桌面，而且在系统树为空的地方，我们的树依然可用。树的弱点是具体的：图标没有名称或名称乱码，控件没有状态，有些元素会出现两次。我们编写的一条节省 token 的清理规则还删掉了关闭按钮的“×”，导致智能体把应用关掉了。我们发布了检测器、截图到树的代码、测试平台、带示例回合的回放查看器、标注方法以及全部结果表格，作为有能力继续推进的团队的起点。

下文所有数字都来自 [`results/`](results/README.md) 中的表格；每个数字之后都注明了来源文件。

---

## 1. 问题与动机

GUI 智能体需要知道屏幕上有什么：存在哪些元素，它们叫什么，位于何处，处于什么状态。常见的信息来源有三类：

1. **截图本身**，由多模态模型读取。
2. **系统无障碍树**（Linux 上为 AT-SPI，Windows 上为 UIA，macOS 上为 AX）。应用实现了它时就很精确，但覆盖范围不均：在我们的考试中，两个 GTK4 应用根本无法提供可用的坐标（[results/R1_main_exam.md](results/R1_main_exam.md)）。
3. **屏幕解析器**，把像素转换成元素列表，例如 OmniParser [1] 或 Screen2AX [2]。

我们的问题是：第 3 种方案能否由一个*小型本地模型*来实现。这个模型把前沿模型“看屏幕”的能力蒸馏成文本形式的树，使智能体——甚至是完全无法看图的智能体——只需读取这棵树。如果可行，这棵树会比像素更便宜，能在无障碍树失效的地方工作，并让纯文本或小型模型也能操作桌面。

我们进行了端到端的测试：标注 → 训练 → 构建树 → 让智能体在真实任务上使用它，并由程序评分。第 5 节说明了这一思路在哪些地方成立，在哪些地方不成立。

## 2. 树是什么

对于每张截图，检测器会以 16 种角色之一提出框选区域（类 ARIA 的角色，如 `aria:button`、`aria:textbox`、`aria:listitem`、`vax:visibleText` 等）。OCR 读取每个框内的文字，该文字即元素的名称。名称从不靠猜测得出：没有可读文字的图标，名称为空。每个元素占一行：

```
role [id] "name" @(left, top, width, height) c=(centre_x, centre_y)
```

下面是一个真实例子：GLM 5.3 Flash 在 Drawing 应用启动后收到的前几行（截图 + 树的条件，坐标位于 1280×720 画面中；回放：[`examples/episodes/r5__glm__drawing_no_ctrl_zoom__H_ours__r0`](examples/episodes/)）：

```
aria:button [e1] "Open" @(7,7,44,22) c=(29,18)
aria:combobox [e2] "" @(57,7,37,22) c=(75,18)
aria:button [e3] "Q √" @(57,7,37,22) c=(75,18)
aria:button [e4] "" @(99,7,23,22) c=(110,18)
aria:button [e5] "" @(123,7,23,22) c=(134,18)
vax:visibleText [e6] "Drawing" @(620,7,39,10) c=(639,12)
aria:button [e7] "Save" @(1119,7,43,22) c=(1140,18)
aria:button [e8] "目" @(1165,7,24,23) c=(1177,18)
aria:button [e11] "×" @(1254,10,16,15) c=(1262,17)
```

**优点：** 带文字的按钮（“Open”“Save”）框得很紧，名称正确，其中心点可以直接点击。GLM 在第二步用 `目` 的中心点打开了菜单，并在五步内完成了任务。

**缺点**，九行之内全部可见：
- 图标按钮没有名称（`e4`、`e5`）；
- 已有的名称往往是对图形符号的 OCR 误读：搜索图标读作 `"Q √"`，菜单图标读作 `"目"`；
- 同一位置出现两次（`e2` 与 `e3` 的框位完全相同）；
- 无法得知开关是开还是关。

格式、JSON 形式、紧凑变体和增量编码记录在 [docs/tree_format.md](docs/tree_format.md) 中。

## 3. 构建方法

### 3.1 框选约定

来自不同来源的标注（DOM、人工数据集、无障碍树、模型标注器）绘制框的方式各不相同：边距宽松、行宽不可见、容器与叶子节点混杂。我们制定了一条统一的约定——“当前所绘内容的紧致框”——并为行、文本行、图标、覆盖层和变暗背景给出了规则。所有标注都使用这一约定（[labeling/box_convention_v1.md](labeling/box_convention_v1.md)）。

### 3.2 前沿模型标注

Claude Opus 依据一个固定的提示词对每张截图进行标注，提示词中写明了该约定（[labeling/prompts/label_rules_v1_1.md](labeling/prompts/label_rules_v1_1.md)）；大屏幕则分块标注后再合并。Claude Sonnet 对样本进行质量复核，被标记的图像进入一轮修复。总计 3,215 张图像（2,912 张训练、303 张考试），按 API 等价费用计算为 $1,044.74，包括质检与修复在内，平均每张约 $0.32（[results/labeling_cost.md](results/labeling_cost.md)）。数据来源包括：在私有虚拟显示器中捕获的真实 Linux 应用截图、公开的 GroundCUA 数据集中的截图，以及公开网站（见 [DATA.md](DATA.md)）。

标注质量如何？第二位标注者（Claude Sonnet，相同提示词，50 张考试图像）与 Opus 标注的类无关 F1 为 0.955（[results/D2_detector_side.md](results/D2_detector_side.md)）。两位标注者来自同一模型家族，并依据相同的规则，因此这衡量的是一致性，而非正确性。

### 3.3 检测器

YOLO11s，输入尺寸 1280 px，在 2,782 张已标注图像上微调 40 个 epoch（单张 A100 上耗时 21 分钟）（[results/D1_detector.md](results/D1_detector.md)）。评估方式：以 IoU ≥ 0.5 进行贪心的一对一匹配；“类无关”忽略角色，“严格”则要求角色一致；阈值 0.25 与 0.45 均有报告，且从未在考试集上调参（[results/D1_detector.md](results/D1_detector.md)）。

| | 留出的 Linux 应用（10 个应用，258 张图像） | 留出的网站（3 个站点，45 张图像） |
|---|---|---|
| 微调后检测器，类无关 F1 @0.25 / @0.45 | **0.854 / 0.874** | 0.787 / 0.813 |
| 同上，严格 F1 @0.25 | 0.798 | — |
| 未微调的起始检查点 | 0.489 / 0.212 | 0.549 / 0.510 |

（[results/D1_detector.md](results/D1_detector.md)）

- **标注差距。** 检测器与每位标注者的一致性约为 0.85（与 Opus 为 0.855，与 Sonnet 为 0.853），而两位标注者之间的一致性为 0.955。模型比标注一致性低约 0.1，因此标注尚未成为上限（[results/D2_detector_side.md](results/D2_detector_side.md)）。
- **起始检查点影响不大。** 我们的起始检查点是在我们不发布的合成数据与网页数据上预训练的。从公开的 COCO YOLO11s 出发，在留出的应用上得分为 0.848，低 0.006（[results/D1_detector.md](results/D1_detector.md)）；在两个随机种子上，差距仍约为 0.01（[results/D2_detector_side.md](results/D2_detector_side.md)）。
- **数据曲线。** 在 303 张的考试集上，使用训练集的 25 % / 50 % / 100 %，分别得到 F1 0.815 / 0.827 / 0.845。数据量每翻一倍仍能增加约 0.012–0.018，且自助法区间都在零以上，因此曲线尚未趋于平缓（[results/D2_detector_side.md](results/D2_detector_side.md)）。
- **鲁棒性。** 深色主题造成 −0.019 的下降，1366×768 屏幕造成 −0.024 的下降（[results/D2_detector_side.md](results/D2_detector_side.md)）。
- **同一考试上的基线。** 经典 CV + OCR 流水线得分 0.623，OmniParser v2 的检测器得分 0.586；差距几乎全部来自召回率（[results/D2_detector_side.md](results/D2_detector_side.md)）。
- **速度。** 检测器在 RTX 2060 上每帧 44 ms，在笔记本 CPU 上为 260 ms（[results/D1_detector.md](results/D1_detector.md)）；加上 OCR 后，智能体运行中一次完整观察约需 0.45 s（[results/R1_main_exam.md](results/R1_main_exam.md)，设备说明见该文件）。

## 4. 测试平台

[`bench/`](bench/README.md) 是一个研究用的测试平台，而非产品。

- **应用与任务。** 8 个 Linux 桌面应用，均不在检测器的训练数据中：Drawing、gitg、KeePassXC、Lutris、Obsidian、Okular（其无障碍树可用），以及 GNOME Calendar 和 GNOME Contacts（其 GTK4 无障碍树不报告坐标）。每个应用有 6 个任务（2 个简单、3 个中等、1 个困难），共 48 个，在首次运行前即已冻结（[bench/TASKS.md](bench/TASKS.md)）。
- **评分。** 智能体结束后，应用被关闭，判分程序（oracle）读取应用实际保存的状态：文件、SQLite、通过数据服务器读取的 iCalendar / vCard、通过命令行读取的 KeePass 数据库、git、PDF 批注、设置。没有人工或模型评判。每个判分程序都经过两项检验：脚本化的正向运行（必须通过）和空操作运行（必须失败）。首次运行后，审计发现了一个解析错误（Okular 将批注保存为新的 PDF 对象代次）。判分程序 v1.1 只修复了这一点，并依据归档的最终状态对每个回合重新评分。
- **环境。** 每个回合都在 1920×1080 的私有 Xvfb 显示器上运行，使用全新的沙盒 HOME，且每次都会重新启动应用。
- **工具。** 智能体通过一个 MCP 服务器恰好获得六个工具：`observe`、`click(x, y)`、`type`、`key`（仅限白名单，不含快捷键）、`scroll`、`done`，调用次数上限为 20 次。
- **条件。** 各条件的差异仅在于 `observe` 返回的内容，以及系统提示词中的一段话：
  - `S_shot`：1280×720 截图；
  - `T_ours`：仅文本形式的我们的树；
  - `T_atspi`：仅文本形式的系统无障碍树；
  - `T_omni`：仅文本形式的 OmniParser v2 输出；
  - `H_ours` / `H_atspi`：截图加树，位于同一坐标系中。

  AT-SPI 基线是刻意从简的：一个扁平列表，包含角色、名称与框，通过坐标点击，没有控件状态，也没有“作用于元素”的接口。
- **锁定。** 智能体 CLI 启动时禁用所有内置工具，只允许六个工具，并在一个空的工作目录中运行。一个探测请求要求智能体读取文件、写入文件、运行 shell 或浏览网页，该探测在所有条件下均通过。
- **外壳。** 使用了两种智能体外壳：`claude -p`（R1、R3），以及 OMP（R5，用于通过 OpenAI 风格接口访问的非 Claude 模型）。对于 OMP，我们 (a) 通过请求钩子用基准提示词替换了其额外添加的系统提示块，(b) 关闭了其自动行为，并且 (c) 加入了一道顺序闸门（§6.4）。我们让 Claude Haiku 分别经由两种外壳运行，以此校准该外壳（[results/R5_four_readers.md](results/R5_four_readers.md)）。

全文使用的实验代号：

| 代号 | 内容 | 读取者 | 规模 |
|---|---|---|---|
| R1 | 主考试，7 个条件 | Claude Haiku（一个条件用 Sonnet），`claude -p` | 48 个任务 × 3 次运行，1,008 个回合 |
| R2 | 树格式的离线 token 核算 | —（无模型调用） | 1,826 条存档观察 |
| R3 | 树优先的智能体，带 hover / look | Claude Haiku，`claude -p` | 48 个任务 × 3 次运行，768 个回合 |
| R4 | 通过另一 CLI 调用 Gemini | Gemini 3.8 Flash | 1 个完整任务（配额耗尽） |
| R5 | 通过同一外壳的四个读者 | GLM 5.3 Flash、DeepSeek V4.1 Flash、LongCat 2.0（仅文本）、Claude Haiku、OMP | 48 个任务中的 27 个 × 1 次运行 |
| D1 | 检测器训练臂 | — | 303 张图像的考试 |
| D2 | 检测器补充实验 | — | 同一考试 + 50 张第二标注者图像 |

## 5. 结果

请只将每个模型与它自己比较。不要跨模型或跨外壳比较绝对数值。R5 每个单元格只在 27 个任务上运行一次，且没有置信区间；因此我们认为该处低于约 15 个百分点的差异尚未确立（[results/R5_four_readers.md](results/R5_four_readers.md)）。

### 5.1 Claude 类智能体不需要树

R1，Claude Haiku，48 个任务 × 3 次运行，成功率及 95 % 任务自助法区间（[results/R1_main_exam.md](results/R1_main_exam.md)）：

| 条件 | 成功率 | 每次成功的美元成本 |
|---|---|---|
| 仅截图 | **86 %** [78, 94] | 0.0057 |
| 仅截图，Claude Sonnet | 85 % [75, 94] | 0.0721 |
| 截图 + AT-SPI 树 | 84 % [74, 92] | 0.0113 |
| 截图 + 我们的树 | 81 % [70, 90] | 0.0146 |
| 仅我们的树 | 57 % [44, 69] | 0.0146 |
| 仅 AT-SPI 树 | 52 % [39, 65] | 0.0133 |
| 仅 OmniParser v2 树 | 44 % [31, 56] | 0.0170 |

- **加入我们的树没有帮助。** 截图 + 我们的树相对于仅截图：−5.6 个百分点 [−13.2, +1.4]；加入 AT-SPI 树则为 −2.1 [−7.6, +2.1]（[results/R1_main_exam.md](results/R1_main_exam.md)）。
- **机制（探索性）。** 在我们的树单独使用时总是失败的 16 个任务上，把它加入截图会造成损害（−20.8 [−37.5, −4.2]）；在其余 32 个任务上则无影响（+2.1 [−2.1, +7.3]）。错误的树会误导；正确的树只是重复了像素中已有的信息（[results/R1_main_exam.md](results/R1_main_exam.md)）。
- **仅用树与其他替代方案相比。** 总体而言，我们的树单独使用与扁平的 AT-SPI 列表持平（+4.9 [−9.7, +20.1]），并优于 OmniParser v2（+13.2 [+2.1, +24.3]）。在两个无障碍树为空的应用上，我们的树领先 +52.8 [+25.0, +77.8]（[results/R1_main_exam.md](results/R1_main_exam.md)）。
- **我们的树为何失败。** 在抽样的失败案例中，树很少漏掉元素（8 个中有 0 个）。它的问题是名称识别错误——例如 gitg 的阶段视图按钮被 OCR 成了“业”——或者是智能体规划失误（[results/R1_main_exam.md](results/R1_main_exam.md)）。
- **通过另一外壳得到相同的排序。** 通过 OMP，Haiku 同样把截图排在树之前：27 个任务中 0 胜、6 负、21 平（[results/R5_four_readers.md](results/R5_four_readers.md)）。回放：[`r5__haiku__gitg_commit_readme__T_ours__r0`](examples/episodes/) 在文件列表与底部按钮之间反复切换后失败；[`r5__haiku__gitg_commit_readme__S_shot__r0`](examples/episodes/) 成功；`claude -p` 的回合 `r1__haiku__gitg_commit_readme__{T_ours,S_shot}__r0` 也呈现相同的走向。

**树优先同样无法挽救（R3）。** 我们给 Haiku 提供了一棵清理过、紧凑的树（每次操作后只发送变化的部分），以及一个 `hover` 工具和一个 `look` 工具（按需返回截图）（[results/R3_tree_first.md](results/R3_tree_first.md)）：
- 成功率为 71 % [59, 83]，而同一批次中的截图智能体为 82 % [72, 91]，差值为 −11.1 [−19.4, −4.2]。
- 它更便宜（每回合成本为 0.75 倍），但更慢（26.0 秒对 21.8 秒）。
- 它并没有真正以树为先：91 % 的回合至少查看过一次截图。

### 5.2 一些非 Claude 读者借助树表现更好

R5，27 个任务，每个单元格运行一次，通过 OMP（[results/R5_four_readers.md](results/R5_four_readers.md)）：

| 读者 | 截图 | 我们的树 | 截图 + 我们的树 | AT-SPI 树 |
|---|---|---|---|---|
| GLM 5.3 Flash | 17/27 | 18/27 | **24/27** | – |
| DeepSeek V4.1 Flash | 19/27 | **22/27** | 21/27 | – |
| LongCat 2.0（无图像输入） | – | **19/27** | – | 15/27 |
| Claude Haiku（外壳校准） | **21/27** | 15/27 | **21/27** | – |

- **GLM。** 截图 + 树是它的最佳条件：比仅截图高出 26 个百分点，按任务计 9 胜、2 负、16 平。这是 R5 中唯一超过我们 15 个百分点标准的差异。
- **DeepSeek。** 仅用树比截图高出 11 个百分点（6 胜 / 3 负 / 18 平）。这低于标准，因此我们只将其视为一个方向。
- **示例（gitg，“stage only README.md”）。** 使用截图的 DeepSeek 用满了全部 20 步，什么也没有暂存。使用树时它也乱试了 12 步；第 13 步时它点击了名为“业”的按钮（即阶段视图切换）。下一棵树中出现了“Staged”和“Stage selection”，它在第 18 步完成了任务。回放：[`r5__deepseek__gitg_stage_readme__S_shot__r0`](examples/episodes/) 与 [`r5__deepseek__gitg_stage_readme__T_ours__r0`](examples/episodes/)；该任务上所有读者的并排比较见查看器的任务页面。
- **不只是点击不准。** 我们的数据没有区分出这些模型受益的原因。点击审计发现，DeepSeek 的截图点击在 24 次中有 24 次命中目标，因此仅凭点击不准并不能解释这一现象（[results/R5_four_readers.md](results/R5_four_readers.md)）。
- **Gemini（R4）。** 在 CLI 配额耗尽前只完成了一个完整任务。合并 5 个任务上所有已评分的回合，得到截图 3/7、树 5/5、截图 + 树 5/5——这是一个方向，而非结果（[results/R4_gemini.md](results/R4_gemini.md)）。

### 5.3 纯文本模型可以通过树操作桌面，包括在系统树为空的地方

LongCat 2.0 无法接收图像。通过我们的树，它完成了 27 个任务中的 19 个（前 24 个中的 18 个）；通过 AT-SPI 列表则为 27 个中的 15 个；按任务计为 7 胜、3 负、17 平（[results/R5_four_readers.md](results/R5_four_readers.md)）。

在 GNOME Contacts 和 GNOME Calendar 上，AT-SPI 列表分别得 0/3 和 0/6，因为那里没有任何元素（[results/R5_four_readers.md](results/R5_four_readers.md)）。回放：[`r5__longcat__gnome_contacts_email__T_atspi__r0`](examples/episodes/) 在每一步都收到“0 个元素”，只能盲目地按 Tab 和 Escape；[`r5__longcat__gnome_contacts_email__T_ours__r0`](examples/episodes/) 则用 8 步创建了联系人。

### 5.4 成本与 token

- **原始树并不比像素便宜。** 我们的树平均每步约 2,040 个 token，是 1280×720 截图（约 1,154 个 token）的 1.6 倍，因为它完整列出了每一个元素（[results/R1_main_exam.md](results/R1_main_exam.md)）。
- **紧凑格式在存档观察上的表现（R2，无模型调用）。** 按回合平均的每步 token 数（[results/R2_token_accounting.md](results/R2_token_accounting.md)）：
  - 原始格式：2,122；
  - 紧凑行：818；
  - 紧凑 + 清理：594；
  - 紧凑 + 清理 + 仅变化部分：271。
- **实时运行中的测量（R3）。** 仅含变化部分的列表，每个列表步骤成本为 385 个 token：每字符的 token 数比估计值高约 15 %，并且有更多步骤退回到完整列表（[results/R3_tree_first.md](results/R3_tree_first.md)）。
- **但智能体把节省的部分花掉了。** 智能体执行了更多步骤，并请求了更多截图，因此成本只降到 0.75 倍，而成功率下降了（§5.1）。

### 5.5 附带发现：去掉多余的 observe 调用

在 R1 中，Haiku 的截图智能体在 1,694 次工具调用中发出了 573 次 `observe` 调用：其中 144 次是回合的第一次调用，另外 429 次紧跟在某个操作之后，而操作本身已经返回了新的观察（[results/R3_tree_first.md](results/R3_tree_first.md)）。移除 `observe` 工具，并把第一张截图附在任务消息中之后，截图智能体既更好又更便宜（[results/R3_tree_first.md](results/R3_tree_first.md)）：
- 成功率 89 % [82, 95]，相对标准截图智能体 +6.9 [+1.4, +13.2]；
- 步数从 11.5 降至 9.0；
- 每回合 $0.0038，原为 $0.0048。

## 6. 负面结果与缺陷

### 6.1 树优先未通过检验

这一工作假设——“小型本地模型构建树，语言模型只读取树”——对于这些应用上的 Claude 类智能体并不成立。无论是仅用树还是树优先，都没有能与截图持平（§5.1）。

### 6.2 树缺少什么

每一项都有一个可回放的回合：

1. **没有名称的图标，或名称乱码的图标。**
   - gitg 的关键切换按钮名为“业”，DeepSeek 花了 12 步才尝试它（[`r5__deepseek__gitg_stage_readme__T_ours__r0`](examples/episodes/)，第 13 步）。
   - 在 R1 的失败样本中，树的主要失败原因是名称错误或乱码，而不是缺少框（[results/R1_main_exam.md](results/R1_main_exam.md)）。
2. **没有控件状态。**
   - KeePassXC 的“保存前备份数据库文件”复选框出现在树中，但没有选中 / 未选中的状态。
   - GLM 在第 4 步勾选了它，第 5 步又再次点击（截图显示 未选中 → 已选中 → 未选中），最终任务失败（[`r5__glm__keepassxc_enable_backup__T_ours__r0`](examples/episodes/)，第 5 步）。
   - 使用截图时它成功了。
3. **重复的行。**
   - 同一个复选框被列出三次：一次作为复选框，一次作为列表项，一次作为文本，框位几乎相同。
   - Drawing 的搜索框出现两次（§2）。
   - 这会使树膨胀。

### 6.3 我们自己的清理规则破坏了关闭按钮

为节省 token，R3 的清理规则会清空小型非文本元素以及纯符号名称的名称。这也清空了标题栏关闭按钮“×”的名称：
- Haiku 把最右侧未命名的按钮当成了菜单，在 144 个回合中有 39 个回合关闭了应用，这些回合全部失败。使用未清理的树时，144 个回合中该情况出现 0 次（[results/R3_tree_first.md](results/R3_tree_first.md)）。回放：[`r3__haiku__drawing_no_ctrl_zoom__X1__r2`](examples/episodes/)，第 2 步。
- 我们的离线检查没有发现这个问题。该检查只检验了成功的智能体点击过的元素，而读取到“×”的智能体从未点击它。

清理代码以实验性质、默认关闭的形式随 `pixeltree/formats/clean.py` 一同发布。

### 6.4 两个值得了解的外壳缺陷

1. **OMP 乱序执行了工具调用。** OMP 将一条模型消息中的所有工具调用同时发送给 MCP 服务器，它们按线程抢到锁的先后顺序执行。Haiku 会批量发出调用，因此文本在字段获得焦点之前就已输入。
   - 在前 24 个任务上，这使 Haiku 损失了 25–45 个百分点：竞争调用时为 42 / 33 / 46 %，按顺序执行时为 83 / 58 / 83 %（[results/R5_four_readers.md](results/R5_four_readers.md)）。
   - 修复：服务器按照模型写出的顺序执行调用，顺序由一个 shell 钩子记录。
   - 修复后，OMP 的结果在几个百分点之内与 `claude -p` 的数字一致。
2. **超出步数上限后的调用。** 在关闭 OMP 的循环保护后，GLM 在超过 20 次调用上限之后仍然调用了约 350 次 `done`。现在运行器会在达到上限后停止 shell（[results/R5_four_readers.md](results/R5_four_readers.md)）。

另外：在项目目录中启动的 CLI 智能体可能会读取项目级的上下文文件。请在空目录中运行智能体。

## 7. 局限

- **R5 尚不完整。** 48 个任务中只有 27 个，每个单元格一次运行，没有置信区间（[results/R5_four_readers.md](results/R5_four_readers.md)）。
- **覆盖范围窄。** 8 个 Linux 应用，屏幕内容相对稀疏：根据应用不同，平均每屏检测到 26–103 个元素（[results/R2_token_accounting.md](results/R2_token_accounting.md)）。密集界面、高 DPI 屏幕、Windows 和 macOS 均未测试。
- **AT-SPI 基线只是扁平形式。** 仅包含角色、名称与框，通过坐标点击，没有状态，也没有元素操作。它并不代表系统无障碍 API 所能提供的上限。
- **Gemini 结果仅为轶事。** 只有一个完整任务（[results/R4_gemini.md](results/R4_gemini.md)）。
- **读取者是云端模型。** 尚未测试任何小型本地模型作为树的读取者。
- **隔离运行。** 所有回合都在隔离的虚拟显示器中运行，且每次都会重新启动应用。拥有多个窗口、通知和个人数据的真实桌面尚未测试。
- **固定日期。** 日历任务假设运行时间位于 2026-11-08 至 2026-11-14 所在的那一周；判分程序使用真实日期（见 [bench/README.md](bench/README.md)）。
- **标注与约定。** 检测器分数是相对于一个模型家族在我们约定下生成的标注计算的；它们不代表其他约定，例如 GroundCUA 的人工框（见 [results/D1_detector.md](results/D1_detector.md)）。

## 8. 给后续研究者的方向

1. **提炼“它是什么”与“它处于什么状态”，而不只是“它在哪里”。** 对于这些应用，框的问题基本已经解决；失败主要来自图标含义和控件状态。一个能为图标命名，并报告已勾选 / 已选中 / 已展开 / 已禁用状态的小型模型，将直接解决 §6.2 中的缺陷。我们的标注方法可以扩展这些字段。
2. **按应用适配。** 数据曲线仍在上升（§3.3），训练集覆盖 148 个应用组，平均每组约 20 帧（[results/labeling_cost.md](results/labeling_cost.md)）。适配一个新应用可能只需要该应用约 100–250 帧自动标注的数据。这一点尚未检验：是我们的估计，而非结果。
3. **谁会受益。** 树对两个非 Claude 的图像模型有帮助，并使一个纯文本模型变得可用。小型本地读取者，以及受益背后的原因（感知、定位还是规划），仍是有待回答的问题。
4. **实时性。** 查看器回放的是已完成的回合。实时模式以及常驻的感知服务（检测器 + OCR 只加载一次）是自然的下一步；在 R1 中，每个回合重新加载模型使第一步增加了约 12 秒（[results/R1_main_exam.md](results/R1_main_exam.md)）。
5. **不要按规则清理。** 如果你要压缩树，也要衡量其对失败回合的损害，而不只是对成功点击的影响（§6.3）。

## 9. 相关工作

- [1] **OmniParser**（Lu 等，arXiv:2408.00203）将截图解析为可交互区域，并为基于视觉的 GUI 智能体提供说明文字。我们使用其 v2 版本作为基线：既作为检测器（§3.3），也作为智能体的文本输入（§5.1）。
- [2] **Screen2AX**（Muryn 等，arXiv:2507.16704）从截图生成分层的 macOS 无障碍元数据。
- [3] **OSWorld**（Xie 等，arXiv:2404.07972）是一个在真实计算机环境中进行开放式任务的基准，采用基于执行的评估。我们的测试平台沿用了同样的思路：对应用的真实最终状态进行评分。
- [4] **OS-Harm**（Kuntz 等，arXiv:2506.14866）在 OSWorld 之上构建了一个面向计算机使用智能体的安全基准。
- [5] **OSWorld-Human**（Abhyankar 等，arXiv:2506.16042）以人类轨迹衡量智能体效率，发现智能体所走的步数远多于必要的数量；可与我们在 §5.5 中关于观察步数的发现对照。
- [6] **“Do GUI Agents Believe Their Eyes?”**（Zhang 等，arXiv:2607.04334）诊断了智能体究竟是信任像素还是结构化文本，并发现它们常常信任过时或错误的结构。这与我们的发现一致：错误的树会误导具备截图能力的智能体（§5.1）。

## 10. 本仓库包含什么

布局与快速开始见 [README.md](README.md)，检测器见 [weights/MODEL_CARD.md](weights/MODEL_CARD.md)，数据来源及哪些内容未被再分发见 [DATA.md](DATA.md)。
