# dialog_render 对话渲染工具

## 功能说明
解析对话讨论YAML脚本，基于Playwright无头浏览器，一次性生成三类输出产物：
1. **交互式HTML网页**：完整对话气泡、角色头像内嵌Base64，分组音频播放器，支持浅色/深色主题切换，播放器互斥（同一时间仅允许一个音频播放）。
2. **A4 PDF打印文档**：适合打印输出，无JS、无音频，气泡+头像完整展示。
3. **分页PNG图片序列**：固定视口 `1080×1920`（9:16纵向）超长内容自动分页截图。

> 逻辑特性
> - 连续同一说话人多条台词自动合并至同一个对话气泡，内部按原台词分段`<p>`换行。
> - 气泡背景色自动提取头像图片主色，通道减半+半透明；头像缺失/图片解析失败回退浅灰色气泡，角色名文本占位。
> - group分组标题渲染；pd为空的group直接跳过渲染；音频文件缺失仅打印警告，不中断程序。
> - PDF、PNG输出不包含音频播放器；只有交互式HTML启用音频与主题切换JS。

## 环境依赖
```bash
pip install pyyaml jinja2 playwright pillow
playwright install chromium
```

## 工程目录布局

```
./
├─ dialog_render.py                     # 主命令行脚本
├─ dialog_interactive.html.j2           # 交互式网页jinja2模板(带主题切换+audio播放器)
├─ dialog_print_pdf.html.j2             # PDF导出模板(打印友好，无JS无音频)
└─ dialog_snapshot_png.html.j2          # PNG分页截图模板
```

### 外部资源目录（用户提供）

```
cast_dir/                               # 角色资源目录(-c参数指定)
   ├─ amy_00001_.png
   └─ bob_00001_.png

audio_dir/                              # 分组合成音频目录(-a参数指定)
   ├─ _groups_0_a.wav
   ├─ _groups_1_a.wav
   └─ _groups_2_a.wav
```

命名约定：

1. 头像：`{sp}_00001_.png`，sp为YAML中pd的角色名。
2. group音频：`_groups_{idx}_a.wav`，idx对应YAML groups数组下标从0开始。

## 命令行调用

```
python dialog_render.py demo_discuss.yaml -c ./cast_dir -a ./audio_dir
```

参数说明：

- 位置参数 `demo_discuss.yaml`：对话脚本YAML路径（必填）
- `-c / --cast_dir`：角色头像资源目录（必填）
- `-a / --audio_dir`：分组wav音频目录（必填）
- `--template_dir`：jinja模板文件夹，默认脚本所在目录

## YAML输入格式简述

```
quiz_meta:
  title: "课堂对话演示"
  subject: "英语情景对话"
groups:
  - g: g0
    gt: "课堂片段一"
    a:
      pd:
        - sp: amy
          txt: "第一句台词"
          gap: 1.2
        - sp: amy
          txt: "同一个人连续第二句台词"
          gap: 1.0
        - sp: bob
          txt: "切换角色后的台词"
          gap: 0.8
```

> 
> gap字段仅用于TTS，渲染HTML/PDF/PNG完全忽略。

## 输出产物

产物全部生成于**输入YAML文件同级目录**。

假设输入文件为 `demo_discuss.yaml`：

1. `demo_discuss_interactive.html`
   - 单文件网页，头像、音频全部base64内嵌，不依赖外部资源。
   - 默认浅色模式，右上角按钮切换深色；audio播放器互斥。
2. `demo_discuss.pdf`
   - A4打印PDF，无JS，无音频播放器，适合打印。
3. `demo_discuss_snap_000.png`、`demo_discuss_snap_001.png` ……
   - 1080×1920纵向分页PNG序列，长内容自动切分多张图片。
