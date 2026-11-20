# 拍纸片，出听写音频

我把自己手抄的单词本拍成照片，让模型认出来，再合成成可以戴着耳机听的音频。数据库就是一张 tsv 表，你随时能改。

两种节奏：

- 读一遍：英文 → 中文
- 读两遍：英文 → 中文 → 英文 → 中文

一开始只是为了自己复习六级词汇，后来发现身边人也想用，就整理成了现在这样。

## 先说缺点

这东西不是全自动，也别指望它全对。

我自己那 10 页笔记跑下来，大概有九成多的词能直接用，剩下的会标成「待核对」让你自己看一眼。原因很实在：手写连笔、`b` 和 `k` 写得像、行与行挤在一起，模型就会读错或者干脆漏掉。我试过付费模型，也没好到哪去，反而漏得更多。

所以做的时候干脆反过来：**拿不准的就不读**。宁可这一页少两个词，也别让一个错词在耳朵里循环几十遍。你看到的 `review` 就是这个意思。

漏词也是同理。有些字迹实在认不出来，或者那一行被切块切掉了，就会少一条。对着照片扫一眼能看出来，补上就行。

## 怎么用

### 不想装环境

去 Releases 下 `cet6-dictation-windows.zip`，解压，进文件夹双击 `cet6-dictation.exe`。浏览器会自己打开一个本地页面，左边填一次 API Key 就能用。不需要装 Python，数据都在你自己电脑上。

Key 在 exe 同目录的 `.env` 里，换电脑把整个文件夹拷走就行。

### 想用命令行

Python 3.10 以上。

```bash
git clone <你的仓库地址>
cd cet6-dictation
python -m pip install -U pip
pip install -e ".[web]"
```

装得慢就换镜像：

```bash
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[web]"
```

老一点的 pip（21.2 那种）装不了这种项目布局，会报 `File "setup.py" or "setup.cfg" not found`，先升 pip。

## 跑一遍

先建目录，把照片按 `01.jpg`、`02.jpg` 排好放进去：

```bash
mkdir -p 批次/10页/input
```

然后四步：

```bash
dictation extract 批次/10页 --provider glm   # 认字
dictation check   批次/10页                  # 生成词表、标可疑
dictation verify  批次/10页                  # 用释义反查，修形近误读
dictation build   批次/10页 --name 10页      # 出两个 mp3
```

`out/` 下面会多出三个文件：读一遍、读两遍、还有一份纯文本脚本。

### 关于 Key

识别要一个能读图的服务，注册后把 Key 填进 `.env`：

```text
GLM_API_KEY=你的key
```

我常用智谱，有免费额度，中文释义认得比较稳。Gemini 和通义也能用，改 `--provider` 就行。

不想注册也有办法：把 `prompts/extract.md` 里的提示词复制出来，照片一起丢给任意能看图的 AI，把返回的 JSON 按页存进 `ocr/p01.json`、`p02.json`，后面 `check` 和 `build` 照旧。

```bash
dictation extract 批次/10页 --provider manual
```

## 中间那张表

所有东西都是围绕 `wordlist.tsv` 转的。音频是它的副产品，改词只改表，再 build 一次就行。

```text
seq	word	meaning	note	status	source
1	century	世纪			ok	p01
292	rape	强奸，强奸罪	字迹像 rope，按释义判定为 rape	ok	p07
```

`status` 四个值：`ok` 进音频，`review` 等你确认，`dup` 是重复，`skip` 是不要。

改完不用把整段音频重做。语音是按文本哈希缓存的，动了一个词就只重合成那一条，几秒钟的事。

## 我踩过的坑

识别这块改过好几轮，现在的默认设置是这么来的：

- 一页从上到下切两块分别认，比整页丢进去准，漏得少
- 拍完先摆正、提一下对比度再放大。两页测下来多认出三个词（83 对 80），不算多，但没坏处
- 认完换另一个模型再看一遍。第二遍多出来的词会标「仅第二遍识别到」，因为第一遍可能真漏了；第二遍没认出来的不拦，它本来就弱
- 释义里冒出数字（比如 `033(注意力)`），基本是串行了，直接标可疑
- 同词根不算误读。`relentlessly` 被「纠正」成 `relentless` 是错的，这种我拦掉了
- 只差一个字母才自动改（`bank`+树皮 → `bark`），差两个就交给你

`verify` 只读文字不看图，所以它修不了「单词和释义一起认错」的情况。那种只能靠人。

## 网页版

```bash
dictation web
```

默认 `http://localhost:8501`。传照片、改表、合成都在这一个页面上。想在手机上拍，加 `--lan`，终端会给出局域网地址，手机连同一个 WiFi 打开就行。

侧边栏能填 Key、测连接。测试发的是一个很小的文本请求，不花图像额度。

## 常用命令

| 命令 | 干什么 |
|---|---|
| `dictation extract <批次> --provider glm` | 识别 |
| `dictation extract <批次> --model glm-4v-plus` | 换指定模型 |
| `dictation extract <批次> --no-cross` | 关掉第二遍复核，快但更容易漏错 |
| `dictation check <批次>` | 出词表 |
| `dictation check <批次> --force` | 重新出词表，会覆盖手改内容 |
| `dictation verify <批次>` | 释义反查 |
| `dictation build <批次> --name 10页` | 合成音频 |
| `dictation web` / `web --lan` | 网页版 / 允许手机访问 |
| `dictation doctor` | 看看依赖和 Key 配好没有 |

## 节奏和音色

默认英文 `en-US-AriaNeural` 慢 15%，中文 `zh-CN-XiaoxiaoNeural` 慢 10%。词与词之间停 900ms，中英之间 200ms，两遍之间 450ms。

想改就复制 `config.example.json` 成 `config.json` 改数字，不用动代码。英式拼写读错的，在 `pronounce` 里加一行，比如 `plough` 读成 `plow`。

## 目录

```text
docs/SOP.md          完整流程，改流程先改这里
prompts/extract.md   识别用的提示词
src/dictation/       代码
packaging/           打包 exe 的两个文件
config.example.json  音色、停顿、读音
```

## 语音是怎么来的

用的是 `edge-tts`，调微软 Edge 的朗读接口，不用 Key，音质还行。但它不是官方接口，自己听没问题，别拿去做大规模分发。

## 其他

代码 MIT。提示词和文档一起开源，随便改。

有 bug 或者更好的识别思路，欢迎提 issue。
