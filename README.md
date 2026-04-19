# Translation-of-DJ2

Divine Journey 2 简体中文汉化同步仓库。

汉化作者：[琅然_](https://space.bilibili.com/356528)、PinkYuDeer、[柠娜](https://space.bilibili.com/383989569)

## 下载

前往 [Releases](https://github.com/PinkYuDeer/Translation-of-DJ2/releases) 下载最新汉化补丁。

每个 Release 包含两个压缩包：

| 文件 | 内容 |
|------|------|
| **DJ2-汉化-x.xx.x-zh-x.zip** | resources 翻译、补汉材质包、帕秋莉汉化材质包、i18n 自动汉化模组 |
| **DJ2-IGI配置-x.xx.x-zh-x.zip** | InGameInfo 屏幕信息显示（血魔法、RF维度、神秘扭曲等） |

## 安装方法

### 汉化补丁

1. 解压汉化压缩包，将文件夹覆盖到游戏整合包版本目录
2. 自行下载 i18n 自动汉化模组（压缩包内已附带）
3. 进入游戏 → 资源包界面 → 加载补汉材质包（放在 i18n 材质包**下面**）
4. 加载帕秋莉汉化材质包

### IGI 配置

解压 IGI 压缩包到整合包目录覆盖即可。

## 翻译协作

翻译在 [ParaTranz](https://paratranz.cn/projects/15018) 上进行，欢迎加入。

## 自动化流程

本仓库通过 GitHub Actions 实现自动化同步：

```
DJ2 上游新 release
    │  (每天自动检测)
    ▼
sync-to-paratranz ── 下载 en_US 原文 → 上传到 ParaTranz
                                            │
                                    翻译者在 ParaTranz 协作
                                            │
                                     (每天自动嗅探变化)
                                            ▼
                                release ── 拉取翻译 → 自动发布 Release
                                            │
                                    仅保留最近 3 个 Release
```

| Workflow | 触发方式 | 作用 |
|----------|---------|------|
| Sync to ParaTranz | 每天定时 + 手动 | 检测 DJ2 新版本，上传原文到 ParaTranz |
| Build Release | 每天定时 + 手动 | 嗅探 ParaTranz 翻译更新，自动打包发布 |

## 仓库结构

```
├── resources/              # ParaTranz 同步的翻译文件 (en_US + zh_CN)
│   ├── betterquesting/     #   任务书
│   ├── contenttweaker/     #   ContentTweaker 物品
│   ├── crafttweaker/       #   CraftTweaker 物品
│   ├── enchantment_descriptions/
│   ├── groovy/             #   GroovyScript
│   └── requious_frakto/
├── resourcepacks/
│   ├── 补汉材质包/          # 50 个模组的补充汉化 (手动维护)
│   └── 帕秋莉汉化材质包-1.12.2.zip
├── mods/                   # i18n 自动汉化模组 (release 时自动更新)
├── igi/                    # IGI 配置和模组 (手动维护)
├── scripts/                # 同步脚本
└── .github/workflows/      # CI/CD
```

## License

[GPL-3.0](LICENSE)
