# KNX SD-WAN V1.0

基于 OpenWrt/fw4、WireGuard 和 LuCI 的远程维护项目。家庭维护网络通过一个客户网关访问客户**真实 IPv4 局域网**；不使用虚拟目的地址映射，不提供家庭默认互联网出口。

这是 **Private 源码归档与脱敏模板版本**，不是已封装的一键安装发行版。未授予开源许可证。仓库私有不等于可以存放密钥或客户资料。

## 能力与边界

- R86S 上统一控制 `on / off / disconnect / reconnect / status`。
- ON：家庭全网段访问当前客户真实 LAN；客户网关私有维护 Wi-Fi/LAN 可访问家庭 LAN。
- OFF：撤销两方向业务路由、授权及定向 conntrack，保留网关 WG 地址的 SSH、HTTP、Ping 管理。
- DISCONNECT：仅移除指定客户 Peer，保存禁用状态。RECONNECT：恢复管理，业务默认 OFF。
- 只从**物理 WAN 有效 DHCP**识别客户网段；WWAN 只作互联网备用，不导入为客户业务 LAN。
- 全局单客户业务归属、两端短租约和失败关闭；WAN 主用、WWAN 备用；真实 DoH 端点刷新。
- LuCI 中文紧凑卡片、可编辑名称/备注、折叠详情、受限 RPC 和操作失败原因。

**实际现场验收仅客户 A。** 多客户框架不等于完成多客户实机验收；重复网段竞争、完整故障恢复、冷启动及所有 KNX 协议均未全面实测。广播/组播发现不因三层路由自动可用。ETS 曾由用户开启 NAT 模式成功连接，不能扩大为全部 ETS 下载场景已验证。

## 源码状态

程序取自实际开发文件的逐文件白名单，不包含生产备份或旧 Git 历史。三个核心文件的原始摘要已与现场检查点核对；其余源文件为本地开发快照，不宣称本次重新读取生产设备逐字节校验。

发布副本仅进行了站点参数模板化、Agent 管理源地址的等价参数化、刷新暂停文件路径规范化，以及离线 UI 测试路径调整。**模板化副本没有替换生产文件，也没有在生产路由器重新部署验收。** `SOURCE-MANIFEST.json` 记录源文件摘要与发布文件摘要，新增模板和文档不伪装为原生产文件。

## 目录

```text
src/common/       两端共享 Lua 库、监控循环与 procd 服务
src/r86s/         控制器、nft guard、LuCI View/RPC/ACL、管理例外
src/cudy/         受限 Agent、WAN/WWAN 检测、DoH 刷新及 hotplug
integration/      人工审阅的 UCI 增量片段，不是完整设备配置
config/           仅示例参数；真实 site.json 被忽略
tools/            本地渲染与审计工具，不连接生产设备
tests/            离线逻辑、模板、语法和安全检查
docs/             架构、部署、安全和验收范围
```

## 本地生成示例

需要 Python 3.10+；仅生成文件，不执行 SSH、UCI 或服务操作：

```sh
python tools/render.py --config config/site.example.json --output ../knx-example-bundle
python -m unittest discover -s tests -p "test_*.py" -v
node tests/luci-view.test.cjs
python tools/audit.py
```

示例网段和 `vpn.example.invalid` 完全是占位参数。真实参数在仓库外准备；不得提交生成结果、真实客户资料、任何密钥或已填写的设备配置。渲染器拒绝覆盖目录、重叠基础网段、危险参数和仓库内输出。

实际安装前必须阅读 [部署指南](docs/deployment.md)，核对设备能力、表号/优先级、SSH 主机指纹与 OpenClash 兼容契约。不要把 `integration/*.uci` 导入为完整配置，也不要在现有路由器直接覆盖根文件系统。

## 日常控制

```sh
knx-customer a status
knx-customer a on
knx-customer a off
knx-customer a disconnect
knx-customer a reconnect
```

LuCI：**服务 → KNX 客户维护**，路径 `/cgi-bin/luci/admin/services/knx-maintenance`。详情内包含操作按钮。近期握手只是隧道活动参考，不等于目标设备在线。

## 文档

- [架构与状态机](docs/architecture.md)
- [部署、验证和回滚](docs/deployment.md)
- [安全模型与限制](docs/security.md)
- [测试与现场验收范围](docs/testing.md)
- [发布副本检查](docs/release-review.md)

后续新增客户必须连同 Peer 归属、管理 guard、私有维护网段唯一性、CLI/RPC 注册及故障关闭一起审查。V1.0 的部分文件仍保留单客户结构和历史集合名；不能仅增加一行登记就声称多客户部署已安全完成。
