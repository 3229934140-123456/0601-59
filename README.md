# test_project

品牌素材项目 - 由 Brand Kit 工具初始化

## 目录结构

```
test_project/
├── source/              # 原始素材源文件
│   ├── images/          # 原始图片
│   ├── fonts/           # 字体文件
│   ├── icons/           # 图标源文件
│   └── raw/             # 原始未处理文件
├── assets/              # 整理后的资产文件
│   ├── images/          # 整理后的图片
│   ├── fonts/           # 整理后的字体
│   └── icons/           # 整理后的图标
├── output/              # 输出文件
│   ├── resized/         # 多尺寸输出
│   ├── palettes/        # 色板文件
│   └── delivery/        # 最终交付包
└── .brand-kit/          # 工具内部文件
    ├── config.json      # 项目配置
    ├── logs/            # 操作日志
    ├── reports/         # 报告文件
    └── cache/           # 缓存文件
```

## 可用命令

- `brand-kit init`    - 初始化项目
- `brand-kit import`  - 导入图片、字体和图标
- `brand-kit rename`  - 按规则重命名文件
- `brand-kit palette` - 提取主色并生成色板
- `brand-kit resize`  - 批量输出多尺寸
- `brand-kit check`   - 检查素材质量
- `brand-kit pack`    - 生成交付包和清单
