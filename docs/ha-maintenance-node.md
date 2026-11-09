# Home Assistant 单向远程维护节点（客户 C）

在现有 R86S / WireGuard / LuCI 控制器中增加 Linux 单接口节点类型 `linux-ha-oneway`。HA 接在客户现有 LAN 上，维护侧经 HA 访问客户 LAN；HA、容器和客户 LAN 不获得通过此隧道主动访问家庭的权限，合法回包允许。

实际部署采用 **Supervisor 管理的本地加载项**，版本 0.1.2；不再让独立 Docker 容器承担长期运行。迁移后的实机评估 `supported=true`、`healthy=true`，未忽略警告或关闭检查。加载项仍是自有社区代码，不代表 Home Assistant 官方审核或提供支持。

## 状态与边界

| 操作 | 行为 |
|---|---|
| 管理在线、业务 OFF | 精确管理地址的 HA HTTP、宿主机 SSH、受限协调 Agent 与 ICMP 保留 |
| 控制端 ON | 有效物理网段、无冲突、本地许可同意后才建立单向路由与 SNAT、授权租约 |
| 控制端 OFF | 先关闭早期防火墙授权，再撤销本节点业务路由与 Docker 正向规则 |
| 断开 / 重连 | 只移除或恢复本节点 Peer；重连默认 OFF |
| HA 本地许可 OFF | 撤销远程业务，不切断管理 |
| HA 本地许可 ON | 只恢复申请许可，仍需控制端显式 ON |
| Agent 故障 / 网段变化 / 租约到期 | 业务关闭；内核租约 45 秒，不依赖 Agent 执行定时关断 |

C 的 OFF、断开、重连使用独立清理路径；其他客户持有业务时 C ON 被拒绝，已有业务保持。项目依然是**全局单客户业务归属**，不能宣称所有客户支持并行业务。旧路由器节点仍保留原控制语义。

当前支持 IPv4、一个明确指定的物理接口和直连私有客户 LAN。网段、网关、邻居 MAC 和本次启动身份绑定候选指纹；不自动选择 Docker 网桥。Endpoint 使用 IPv4 地址或解析 A 记录的域名。没有广播/组播发现或其他 VLAN 的保证。

## 加载项源码与私有数据

`src/ha_node/` 是可完整复制的本地加载项源码：Dockerfile、config.yaml、文档、Python Agent、规则执行器和健康检查。无密钥、真实设备配置或已填写的认证信息。

加载项使用宿主网络和 `NET_ADMIN`，保护模式开启；不申请 full_access、Docker socket、Supervisor 或 HA API 权限。启动由 Supervisor 的 `boot=auto` 管理，停止宽限 30 秒。容器 PID 1 转发停止信号，让 Agent 清理规则、策略路由及自有 WG 接口后退出。配置键见[官方配置参考](https://contributors.home-assistant.io/apps/reference/configuration/)。

私有数据在 `/data/node`，`/state` 是容器内部指向它的符号链接。包含：

- `config.json`：管理员在设备上填写的网络与服务端公钥；
- `wg_private`：设备独立生成的 WG 私钥；
- `ssh_host_ed25519_key`：受限 Agent 独立主机身份；
- `authorized_keys`：仅协调公钥，限制到服务端 WG 源地址；
- `consent_token`：仅回环许可 API 的随机令牌；
- `consent.json`：本地许可；业务 ON 状态不跨进程持久化。

这些文件均不得加入 Git。完整 HA 备份会包含加载项私有目录；实机已经检查备份中确实含有上述关键文件，未输出内容。备份不是 eMMC 全盘镜像，未做实际还原演练。

## 部署顺序（人工审阅，不是一键安装器）

下述路径针对已测试的 HA OS / Supervisor 组合。命令在 **HA 宿主机 root 终端**执行，不是在 Windows PowerShell；其他版本先核对实际 apps/addons 路径。

1. 备份 HA、R86S 本轮相关文件和注册表，验证独立回滚。先读取 A/B 当前状态与 Peer 摘要；不为测试 C 而关闭既有业务。
2. 复制 `src/ha_node/` 到宿主机本地应用目录的 `ha_remote_node/`，刷新应用商店，安装 `local_ha_remote_node`；**先准备配置，再启动**。
3. 在设备私有 `/data/node` 生成独立密钥，可用已安装的加载项镜像执行 `python /app/bootstrap.py keys`。把 WG 公钥登记到 R86S；私钥留在设备。服务端另生成 C 专用协调身份，只交付其公钥到节点。
4. 用 `integration/ha-node/config.example.json` 在设备上准备 `config.json`。所有地址、Endpoint、接口及公钥先核对；示例中的占位公钥不能启动真实服务。
5. 节点 `authorized_keys` 使用 `restrict,from="10.62.0.1"` 和协调公钥。核对 Agent 主机公钥后登记到服务端可信记录；不同 Dropbear 版本对非默认端口的主机匹配方式需实测，不能无条件接受未知密钥。
6. 按下节增量修改 R86S：初始只允许 C 管理 /32，保留精确管理权限及原有客户端。不要导入整份 UCI、重建公共 WG 接口或整份覆盖防火墙。
7. 启动加载项，验证新握手、真实 HTTP、SSH 公钥认证和 Agent `probe`。故障时关闭加载项并按本轮所有权清理；管理不能恢复或必须整机重启时停止推进。
8. 迁移时只运行一个节点实例。验证新加载项后停止旧独立容器并关闭旧容器自启，保留镜像及状态作回退；否则两个实例可能争用同一 WG 接口。
9. 配置 HA 本地许可与业务状态实体。`integration/ha-node/package.yaml` 引用 `!secret`；在本机 secrets 中填写与私有 `consent_token` 对应的 Bearer 值，不写入仓库。勿覆盖已有 packages 配置。

许可 API 仅绑定宿主机回环地址，GET/POST 均认证。受限 Agent 在 WG 管理地址上监听专用 SSH 端口；强制命令只转交 `probe/activate/renew/deactivate`，没有任意 Shell、转发或 TTY 权限。日常宿主机 root SSH 与协调密钥是不同用途。

## R86S 增量接入

本节地址与身份仅为示例，C 没有虚构的私有维护 LAN。控制器注册项：

```json
"c": {
  "id": "c",
  "peer": "knx_customer_c",
  "tunnel": "10.62.0.13",
  "profile": "linux-ha-oneway",
  "agent_port": 22223,
  "agent_key": "/etc/knx-direct/c_id_ed25519"
}
```

Peer 的持久和运行 AllowedIPs 初始仅为管理 /32，不复制其他节点密钥。添加明确的管理路由与禁用状态；`c-state` 初始 `off`。LuCI 注册表增加相同 ID、Peer 和 WG 管理 IP、`profile: linux-ha-oneway` 及名称/备注。**不要给 C 填旧路由器的 `lan` 字段来绕过模型检查。**

原早期 guard 和 fw4 正向链都要增量保留家庭源到 C 管理 /32 的精确 TCP（HA HTTP、宿主 SSH、协调端口）与 ICMP；保留反向原始方向的拒绝。已有新建流不能因普通 `established` 放行绕过撤权。示例管理端口为 80、8123、22222、22223，按现场实际范围审查，不开放整个 WG 网段。

控制器与 RPC/View 更新已经包含可选 HA 类型、独立 C 生命周期、候选拒绝原因和本地许可显示、HA 管理链接。旧的 `tools/render.py` 仍渲染基础 A 型站点，**不会自动合并 C 登记和现场防火墙增量**。发布模板没有被重新部署到现场。

HA 执行层只拥有 `ha_remote_node` nft 表、专用 WG 接口和独立策略表；Docker `DOCKER-USER` 仅添加带本功能标记的限定规则。宿主默认路由及其他应用规则保持。业务规则内核 lease 在已有会话放行前生效；关闭顺序为防火墙先、路由后。

## 验收

见[本次验证记录](validation-2026-11-09.md)。当前 HA 在家庭网络，必须因重叠拒绝 ON；不能改地址声明或绕过冲突来模拟客户现场成功。搬到独立网络后仍需验证正向访问、SNAT 回包、客户/HA 新建反向连接拒绝、已有会话撤权和完整冷启动。
