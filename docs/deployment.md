# 部署指南：人工审查、分阶段、默认 OFF

本次发布没有连接或修改生产路由器。以下是未来维护窗口中的安装说明，**不是本次已执行的动作**。没有一键远程安装器，避免把模板直接覆盖到已有网络。

## 1. 适配条件

- 现场基线：R86S/iStoreOS 24.10 系列、Cudy TR3000/ImmortalWrt 24.10 系列，fw4/nftables、IPv4 WireGuard。
- Lua 5.1、`luci.jsonc`、`nixio`/`nixio.fs`/`nixio.util`、Lua UCI、rpcd、LuCI JavaScript View；不能只假设“有 LuCI”就具备所有 Lua 兼容模块。
- `wg`、支持 JSON 和策略端口选择器的 ip-full、conntrack、ubus、jsonfilter、curl（有效 CA 和 HTTPS）、sha256sum、setsid、procd、BusyBox 常用工具。
- 两端 SSH/Dropbear 版本须实际支持强制命令及使用中的客户端参数；不能拿 OpenSSH 参数文档代替目标 dbclient 验证。
- 两端时间、MTU、WAN DHCP、LAN 加密、管理访问、WG 管理路由已正确配置。不要把客户网络接入私有维护 bridge。
- 保留路由表 189–193 及文档所列优先级、源端口段；逐项检查已有 VPN、策略路由和代理冲突。

## 2. 本地准备

从示例参数制作**仓库外**真实配置：基础网段、WG 地址、Endpoint 域名、物理 WAN 设备名和 UCI Peer 节名。模板不保存客户实际业务网段，Agent 运行时从物理 WAN 识别。

```sh
python tools/render.py --config /private/location/site.json --output /private/location/new-bundle
```

示例 `.invalid` 域名不会建立连接。基础网段需互不重叠；不要把域名或密钥写进文档、提交说明或 shell 历史。`rootfs` 是文件布局参考，`integration` 是增量 UCI 审阅片段。**禁止 `uci import network` 替换整份配置，禁止无审阅 `cp -a rootfs/* /`。**

## 3. 在设备上独立备份与回滚

在两端 root-only 目录（700）保存即将涉及的原文件、UCI 和规则状态；敏感备份文件 600，留在各自设备，不放入 Git。确认恢复动作只针对本轮拥有的文件、策略、集合和 Peer，不能恢复整个系统或清空 nft/conntrack。

在更改前验证 `setsid`/procd 下的延时标记探针：断开原 SSH 后，用新会话确认它确实执行。再安排独立 3–5 分钟回滚，动作须先关闭业务 gate，撤销本轮所属业务路由，恢复被替换的文件；不自动 ON，不重建整个 WG。准备本地 LAN 管理入口。确认管理、语法、默认 OFF 和数据路径后才取消保护。这里未提供未经新环境验证的通用回滚脚本。

## 4. 密钥与受限 SSH（仅设备内配置）

分别生成新的 WG 密钥和控制器专用 SSH 密钥，不复用个人私钥。所有真实密钥、公钥身份清单、authorized_keys 和 known_hosts 均不进入仓库。

- 控制器专用私钥路径为 `/etc/knx-direct/id_ed25519`（目录 700、文件 600）；需要目标 dbclient 支持的格式，不要凭文件名推断格式。
- 在 Cudy 安装 Agent 并限制此钥：forced command `/usr/sbin/knx-direct-agent`，禁止端口转发、agent/X11 转发和 PTY。核实当前 Dropbear 对这些选项确实支持，不支持则停止，不降级为任意 root shell。
- 通过已经可信的本地/WG 管理通道独立读取 SSH 主机公钥指纹，与 R86S 的 `/root/.ssh/known_hosts` 逐一核对后固定；不能只用未核验的 ssh-keyscan 结果建立信任。
- 当前控制器使用固定管理源地址、BatchMode、PasswordAuthentication=no、StrictHostKeyChecking=yes，以及有界执行超时。验证目标 dbclient 的实际参数语义与指纹格式。
- 测试 `probe` 返回合法候选/等待状态，非法命令和错误来源被拒绝，关闭密码回退。不要为省事禁用主机校验。

V1.0 的 Peer 恢复代码没有完整 PSK 重新装载逻辑；**不要将需要 PSK 的 Peer 当作已支持场景部署**。扩展前需单独实现、审查和验证，禁止将 PSK 放进模板。

## 5. 安装文件和增量配置顺序

1. 对照生成的 MANIFEST 安装共享库和 Agent；目录、JSON、私钥为 root-only，执行脚本 700，LuCI 静态文件/菜单/ACL 644，rpcd 后台 700。不要给 Web 进程写入核心脚本的权限。
2. 在 Cudy 和 R86S 分别审阅 `integration`：独立 `knx` 区、input/forward REJECT、仅指定管理例外；R86S 添加新 WG listener，不改个人 WG。密钥只在设备内补入；Cudy 不设 WG 默认路由。
3. 两端放置 nft 定义和早期 guard。R86S `a-gate.nft` 初始为空；known 只预置私有维护 LAN，真实 WAN 候选以后逐步登记；安装私有维护到家庭路由器的租约 input 片段。
4. fw4 include 在重载后调用 reset/reconcile，安全回到 OFF。在加载正向 UCI 规则前，确认早期 guard 已编译到规则集，不能出现“正向规则已开但 guard 缺失”的窗口。
5. Cudy 表 189 需要家庭前缀经 `wg_home` 及 unreachable 默认；在既有 WG 接口事件上调用 hotplug 中相同逻辑或明确初始化，不重建运行中的 WG。表 190/191 的业务路由只能由控制器创建。
6. R86S 保留正确的 1700/1702；不得增加旧的私有 LAN → main 优先级 1701。不要与 Cudy 的合法同号规则混淆。
7. Cudy 的物理 WAN/WWAN 保持已有 DHCP 客户端和 LAN→WAN/masquerade。合并 WAN metric 30、WWAN metric 20、defaultroute=1。健康管理器只拥有 WAN metric 10 路由；不要导入已有旧 Endpoint 主机路由。确认当前 netifd 实际支持 `nohostroute=1`。
8. Endpoint 定时器及 hotplug 只刷新实际公网地址，DoH 失败保留旧地址。`/etc/knx-wg/endpoint.hosts` 目录需先建立（700）。如果希望系统 DNS 使用缓存文件，人工把该文件接入既有 dnsmasq addnhosts；模板不替换全局 DNS。OpenClash fake-ip-filter 排除 Endpoint 域名，并使用更新后仍保留的配置方式，不能关闭 Fake-IP 检查替代此步骤。
9. 健康探测包装器 GID 65534 和可选 OpenClash hook 必须与实际代理绕行契约匹配。可选 hook 默认不生成；未经验证不要启用，不能强行复制表号/fwmark。
10. 开启 `knx-direct`、`knx-wg-ddns`、`knx-uplink` 的 procd 服务前做本地 dry-run、依赖检查和恢复保护。LuCI 菜单/ACL/后端就绪后只作可控 rpcd 局部更新，不重载整个网络来修页面。

## 6. 必须验证后才能授权业务

在设备内检查 Lua/shell 语法、`fw4 check` 和生成规则的 `nft -c`。本仓库的 Windows 离线检查不能代替真实 fw4 环境。

先确认 OFF、Peer 存在、近期握手、全家庭源到管理地址的 TCP 22/80/ICMP，且两方向业务阻断。没有物理 WAN DHCP 时 ON 必须拒绝，不可把 WWAN 热点当客户 LAN。

之后在明确可中断的维护窗口进行 ON→OFF→ON→OFF；核实完整三层路由、源地址、SNAT、真实业务新连接与既有 TCP/UDP 撤权。不得用“接口存在”“握手成功”代替数据面验证，不得以双网卡直连或缓存页面造成假阳性。最终 OFF；确认恢复保护没有残留自动 ON 动作。

## 7. 回滚与升级

先按原可信管理入口 OFF，再停止本次服务，确认租约为空，撤销本程序所属路由/策略及 Peer 业务 AllowedIPs，逐文件恢复备份和原 UCI 增量。Peer 的独立 disable 状态要保留。不要全局 flush，也不要把对端设备备份恢复到本机。

若配置了新环境但尚未取得可靠管理回程，不能远程试错；保留本地入口并停止。真实 WAN 断线/变网段必须失效关闭，需人工复核候选再 ON。更新源码不代表自动升级或向生产推送，本仓库不含生产连接脚本。
