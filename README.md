# WarThunder-Yokonex

《战争雷霆》Yokonex GameHub 联动插件。

通过游戏本机 `127.0.0.1:8111` 遥测接口采集空战、陆战和 CAS 数据，再交给 Yokonex GameHub 触发役次元 IM、蓝牙设备或手机中继反馈。

## 功能

- 空战过载连续联动，以及中等、高、极限过载事件。
- 空战击杀、死亡和坠毁事件。
- 陆战速度连续联动，以及低、中、高速事件。
- 陆战击杀、死亡、维修开始和维修完成事件。
- 陆战空中支援自动切换过载联动，返回坦克后恢复速度联动。
- 战斗开始和结束自动发送 `_stop_all`。
- 后台无窗口运行、单实例保护、自动重连和动态事件映射。
- 多设备分别使用 GameHub 中各自配置的波形和强度。

全部事件见 [使用教程](USAGE.md)。

## 工作原理

```text
战争雷霆 :8111
      │
      ├─ /state、/indicators ── 过载、速度、维修、载具类型
      └─ /hudmsg ───────────── 击杀、死亡、坠毁
                    │
                    ▼
          WarThunder-Yokonex
                    │
      ┌─────────────┴─────────────┐
      ▼                           ▼
GameHub /v1/events        GameHub /ws/plugin
离散事件与 commandId       过载、速度连续比例
      │                           │
      └─────────────┬─────────────┘
                    ▼
          役次元 IM / 本机设备 / 手机中继
```

连续输出会读取当前 `commandId` 在 GameHub 中映射的设备波形，以该波形的 A/B 峰值作为上限，再按实时过载或速度比例缩放。插件本身不维护设备原生强度上限。

## 安装

1. 从 [Yokonex GameHub 官网](https://game-hub.ycygame.net/) 下载并安装最新版 GameHub。
2. 从 [GitHub Releases](https://github.com/CharmingQiann/WarThunder-Yokonex/releases) 下载插件 ZIP。
3. 按照 [USAGE.md](USAGE.md) 完成导入和配置。

## 项目结构

```text
war_thunder_yokonex/   插件核心代码
tests/                 自动测试
main.py                程序入口
manifest.json          GameHub 插件清单与事件定义
config.json            用户配置模板
build.ps1              Windows 发布脚本
USAGE.md               用户教程
CHANGELOG.md            更新记录
```

## 开发环境

- Python 3.12
- Windows 10/11
- Yokonex GameHub

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
```

## 测试

```powershell
python -m unittest discover -s tests -v
```

## 构建

```powershell
.\build.ps1
```

发布包生成到：

```text
artifacts\WarThunder-Yokonex-Plugin-v1.1.1.zip
```

## 相关项目

- [Yokonex GameHub 官网](https://game-hub.ycygame.net/)
- [YOKONEX OpenSource](https://github.com/YCY-YOKONEX/YCY-YOKONEX-OpenSource)
- [War Thunder localhost API documentation](https://github.com/lucasvmx/WarThunder-localhost-documentation)

## 许可证

[MIT](LICENSE)
