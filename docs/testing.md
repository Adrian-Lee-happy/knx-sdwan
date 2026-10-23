# 测试与现场验收记录

## 现场 V1.0（客户 A，2026-10-23）

下表为已完成的原部署验收摘要，不含现场地址、客户清单或运行日志。不是本次发布重新操作生产设备的结果。

| 项目 | 证据与结论 |
|---|---|
| 家庭 → 客户两个已知 Web 设备 | ON 真实 HTTP 成功，OFF 新请求失败，重新 ON 恢复；用户现场亦确认 |
| 私有维护 Wi-Fi → 家庭路由器/存储管理页面 | 用户真实终端确认 ON 成功、OFF 无法新打开；不是把网关源测试冒充 Wi-Fi 终端 |
| 既有四条 TCP 业务会话 | 切换前持续有应答；OFF 后同一 socket 无响应，针对性 conntrack 已清理 |
| 既有普通 UDP 测试会话 | ON 有受限诊断回显，OFF 同一 socket 无回显，再 ON 恢复；不等同完整 KNX 协议验收 |
| 动态状态 | 原入口执行 ON→OFF→ON→OFF；期间用户另有认证 UI 操作，记录按实际状态归类；最终独立复核 OFF |
| 管理 SSH/HTTP | 各阶段均实际成功，OFF 保留管理，近期 WG 握手；不是逐包零丢失测量 |
| 有线 WAN 独立互联网 | 真实 HTTPS 成功，WWAN 已离线；不是只看默认路由配置 |
| 业务路由/AllowedIPs/短租约 | ON 重建，OFF 撤销，最终 Peer 仅保留管理 /32，默认 OFF |
| ETS | 用户此前启用 NAT 模式后成功连接 KNX IP 接口；最终动态轮次没有写入或下载 |
| 无关配置 | 没有重启/重载网络或 OpenClash；相关网络/防火墙文件未变，个人 WG Peer 归属摘要保持；不扩大为全部应用回归 |

这足以判定**当前客户 A 的 V1.0 现场功能验收通过**；不意味着所有设备、所有终端、所有故障模式都已验证。

## 仅代码/规则检查或尚未验证

- 客户上游源伪造、多客户相互攻击及重复网段实际竞争：未做实机攻击或多客户验收。
- 无热点冷启动、全机重启、故意断 WAN、网关黑洞、DHCP 换网段和协调失败的完整故障注入：未全面实测。
- 所有 OpenClash/硬件加速组合、ON 中刷新后的现场动态回归：未全面验证。
- KNXnet/IP 长期 UDP 保持、所有 ETS 工程下载、广播/组播发现、厂商专有协议和所有 MTU/ALG：未全面验证。
- Wi-Fi 终端精确存活 socket 生命周期：由网关源受控连接测试与用户终端新请求反馈分别证明，不能混写。

## 发布副本的本地检查

本地检查只验证脱敏模板及程序的可审查性质，不修改生产路由器：

```sh
python -m unittest discover -s tests -p "test_*.py" -v
node tests/luci-view.test.cjs
python tools/check_syntax.py --bundle /private/location/example-bundle
python tools/audit.py
gitleaks dir . --redact --no-banner
```

Lua 检查使用本机 `lupa.lua51` 的 loadstring，依赖须安装在仓库外；shell 使用本地 Bash `-n`；LuCI JS 使用 Node 语法及模拟 RPC/DOM。JSON 逐文件解析；nft 模板检查参数已消除、协议/网段/租约结构，但 **Windows 本地未执行 Linux nft/fw4 内核编译**，部署前必须在隔离目标环境补做 `fw4 check`/`nft -c`。

单元测试覆盖模板参数拒绝、禁止覆盖/仓库内生成、Lua IP/网段辅助函数、健康状态机、Agent 无物理 WAN 时拒绝候选和 ON，以及离线 UI 名称备注/状态/错误提示。Mock 测试不能替代真实两端协调、隔离攻击或故障注入。

本地运行结果与工具版本记录在 [发布审查记录](release-review.md)。原始站点证据保留在私有本地/设备目录，不随源码上传。

## 下一次现场/实验室验收

使用独立 DHCP 测试 LAN 和可控 HTTP/UDP 设备，先证实默认 OFF；确认无 ETS 写入后测试 ON/OFF 活动连接，再测试单 Peer 断开/恢复、WAN/WWAN 切换与重启恢复。多客户需两台独立网关、可重复的真实网段和攻击源。全过程保留管理 /32，自动恢复只可恢复安全 OFF，不自动 ON。
