# 🔌 v0.5.0 积木代码生成与开发板实测

在通信实验室打开 **🔌 开发板**，选择语言、板型和实验示例。工作台直接使用画布中的积木和参数生成程序。选择某一块积木可定位源码行，选择带积木标记的代码行可回到画布。同一位置显示电脑参考输出与本次板端回读。

## 选择目标

| 目标 | 交付内容 | 部署方式 |
| --- | --- | --- |
| C++ | `main.cpp`、`CMakeLists.txt` | 用 Pico SDK 构建 UF2，选择 BOOTSEL 盘写入 |
| MicroPython | `main.py` | 安装板型对应的解释器 UF2，再上传脚本 |

两种语言均支持第一代 **Raspberry Pi Pico** 和 **Pico W**（RP2040）。源码 ZIP 含独立工程文件及 `experiment.json`，记录工件标识、积木对应的源码行和桌面参考结果。生成范围为固定比特、重复码编译码、BPSK 调制解调、理想信道、UART 回环和信宿组成的线性工程。每块最多输出 2048 个值。实验工具继续在电脑上执行。

## 准备本地工作台

1. 在连接开发板的 Windows 电脑启动 RandomSign，通过 `http://127.0.0.1:8000` 打开通信实验室。电脑端 Python 环境按 `requirements-repro.txt` 安装，其中包括 pyserial 和 mpremote。
2. C++ 构建需要 Pico SDK、Arm GNU 嵌入式编译器、CMake、Ninja 和 SDK 使用的 picotool。可使用 Raspberry Pi 官方 Pico VS Code 扩展安装工具链。工作台会检查用户目录的 `.pico-sdk` 和系统工具。独立 SDK 可设置 `PICO_SDK_PATH`，编译器目录可设置 `PICO_TOOLCHAIN_PATH`，设置后重新启动工作台。[官方 Pico SDK 安装说明](https://www.raspberrypi.com/documentation/microcontrollers/c_sdk.html)
3. 使用 MicroPython 时，按住 BOOTSEL 接入 USB，在出现的 RPI-RP2 盘复制对应板型的官方 UF2。板子重启后，刷新设备列表并选择 USB 串口。[Pico 固件](https://micropython.org/download/RPI_PICO/) [Pico W 固件](https://micropython.org/download/RPI_PICO_W/)

## 实验一 板端 BPSK

1. 载入 **板端 BPSK 收发**，保留默认信源 `1011` 和三次重复编码。查看 C++ 和 MicroPython 下同一块积木对应的算法。
2. 重复编码输出为 `111 000 111 111`。BPSK 将 0 映射为 +1，将 1 映射为 −1。理想信道保留符号，接收端按符号正负判决，再按每组三位的多数值恢复 `1011`。
3. 在 **部署与实测** 中选择板型。C++ 先点 **编译固件**，按住 BOOTSEL 连接板子，刷新并选择对应启动盘，再点 **烧录固件**。MicroPython 选择已安装解释器的目标串口后点 **上传程序**。写入前核对设备名和板型。
4. 重新上电，刷新并选择运行态 USB 串口，点击 **运行并回读**。板子收到匹配当前工程的运行命令后采集各节点。点击调制积木对照符号，点击信宿查看恢复比特。**导出测量 JSON** 可保存此次设备结果。

## 实验二 UART 实物回环

1. 载入 **UART 实物回环**。在同一块板上用跳线连接 **GP0（UART0 TX，物理针脚 1）** 和 **GP1（UART0 RX，物理针脚 2）**。USB 单独负责程序部署和结果回读。[RP2040 串口参考](https://docs.micropython.org/en/latest/rp2/quickref.html#uart-serial-bus)
2. 在电脑上先点 **Build** 和 **Run**。默认 12 位编码数据打包为 `E3 F0`。有效数据从各字节的高位开始填入，尾字节低四位填零，解包后保留原来的 12 位。UART 外设使用 8N1 格式。
3. 按上一实验的步骤部署并回读。接通跳线时，默认向量的预期结果为收 1 帧，恢复 4 位，误比特 0。运行结果以实际接收数据为准。
4. 拔掉跳线，保留 USB，再点击 **运行并回读**。预期结果为收到 0 帧、丢失 1 帧、比较位数 0，BER 显示「无可比较数据」。重新接好跳线即可再次测量。

板端回传包括本次运行随机标识与工件标识。工作台根据节点数量、顺序、长度、指标和当前工程核对收到的报告。USB 通信异常显示为设备错误，UART 数据引脚接收超时则作为该次实验的丢帧结果。

## 验证记录

两种板型的 BPSK 和 UART 共四份 C++ 固件已使用 Pico SDK 2.3.1 和 Arm GNU 15.2.1 构建，picotool 已核对 UF2 的 RP2040 目标与板型。四份 MicroPython 程序已用 mpy-cross 1.29.0 编译，并在 MicroPython 虚拟机上验证 BPSK、模拟串口回显和超时。发布附件中的示例包提供对应的源码与四份 UF2。下面是课堂或实验室设备接入后可执行的实体板验收表。

| 板型 | 语言 | 冷启动与 BPSK 逐块对照 | UART 接线收帧 | UART 拔线超时 |
| --- | --- | --- | --- | --- |
| Pico | C++ | 待实测 | 待实测 | 待实测 |
| Pico | MicroPython | 待实测 | 待实测 | 待实测 |
| Pico W | C++ | 待实测 | 待实测 | 待实测 |
| Pico W | MicroPython | 待实测 | 待实测 | 待实测 |
