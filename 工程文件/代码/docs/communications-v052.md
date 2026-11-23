# 🔌 v0.5.2 ESP32 接入与双板 UART 收发实验

打开 **通信实验室 → 开发板**。原有六个单板示例支持 Pico、Pico W 和 ESP32-S3-DevKitC-1-N8，每款板均可生成 C++ 或 MicroPython 工程。加载「双板传中文」「双板 PN 序列」或「双板 Hamming 纠错」，工作台将显示发送端和接收端两张卡片。

## 拼接和导出

将「板间 UART」放在信源或发送编码器之后，在它后面拼接译码器和信宿。一个板间 UART 对应一条跨板数据线，两端分别选择板型和语言。在「积木与源码」中选中积木可打开本端源码，点击源码中的标记行可定位到画布。UART 在两端均有实现，切换工程文件可查看各自的发送或接收代码。

「下载工程 ZIP」包含 `tx/`、`rx/` 以及桌面参考帧。两组学生也可各自下载本端源码。每个端点的 `experiment.json` 保存本端程序标识、节点参考值和源码行号。

## 构建与接线

| 目标 | C++ | MicroPython | 实验数据引脚 |
| --- | --- | --- | --- |
| Pico / Pico W | Pico SDK 生成 UF2，选择 BOOTSEL 盘写入 | 安装对应板型的解释器，通过 USB 上传 `main.py` | GP0 发送，GP1 接收 |
| ESP32-S3-DevKitC-1-N8 | ESP-IDF 生成包含启动程序、分区表和应用的 BIN，通过板载 USB 转 UART 接口写入 | 安装 ESP32_GENERIC_S3，通过解释器控制台上传 `main.py` | GPIO17 发送，GPIO18 接收 |

使用 ESP32 C++ 时，从已激活的 ESP-IDF 终端启动本地工作台，保留 `IDF_PATH`、`IDF_PYTHON_ENV_PATH` 和工具链 PATH。独立工程可在本端目录执行 `idf.py build` 和 `idf.py -p PORT flash`。Pico 使用现有的 Pico SDK 工具链。[ESP-IDF 环境](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/get-started/) [MicroPython 固件](https://micropython.org/download/ESP32_GENERIC_S3/) [Pico 安装说明](communications-v050.md)

两板各用 USB 供电，发送端 TX 接接收端 RX，两板 GND 相连。例如 Pico 向 ESP32-S3 发送时，连接 GP0 和 GPIO18。在「部署与实测」中分别选择两端的设备并写入对应程序，再选择两个运行态 USB 串口，点击「运行双板实验」。接收板初始化 UART 并通过 USB 报告就绪，工作台随后启动发送板。两端之间的载荷经 UART 传输，两路 USB 分别负责控制和回读。[ESP32-S3 板卡引脚](https://docs.espressif.com/projects/esp-idf/en/v5.3.1/esp32s3/hw-reference/esp32s3/user-guide-devkitc-1.html)

## 三个实验

| 示例 | 操作 | 可观察结果 |
| --- | --- | --- |
| 双板传中文 | 默认发送“你好，ESP32”，切换两端的编程语言 | 发送 14 个 UTF-8 字节，接收信宿按实际比特恢复文字 |
| 双板 PN 序列 | 默认发送 PRBS7 的 127 位 | 载荷占 16 字节，逐位比较覆盖原始 127 位。数据线断开时报告超时 |
| 双板 Hamming 纠错 | 发送 `1011`，在接收板上将第一个码字的第 5 位翻转 | 线上码字为 `0110011`，软件注错后为 `0110111`，综合征为 5，恢复 `1011` |

## 帧与结果

单次运行传输一帧。帧头由 ASCII `RS`、版本字节 1、16 位序号和 16 位有效位数组成。两个整数均为大端序。载荷从每字节最高位依次填入，尾字节用零补齐。末尾的 CRC-16/CCITT-FALSE 覆盖帧头和已装包的载荷。接收端检查帧格式、长度、CRC 和本次序号，再把实际收到的有效位交给接收积木。板端沿用每个积木最多输出 2048 个样本的限制。

结果按帧号并排展示发送值、实际收到的原始位和线上 CRC。接收端读到完整帧时会回传载荷字节和实际序号，电脑独立复算校验。即使 CRC 报错，仍可在面板比较收到的原始位。BER 由发送端实际信源和接收端实际信宿计算。超时、坏帧或序号错误记为一次丢帧，比较位数为零。导出的测量 JSON 同时记录两端程序标识、实际节点、CRC 状态和本次运行标识。

本版采用电脑参考、跨语言串口模拟、MicroPython 虚拟机和固件交叉编译验收。实体板接线、烧录、冷启动及回读验收待完成。
