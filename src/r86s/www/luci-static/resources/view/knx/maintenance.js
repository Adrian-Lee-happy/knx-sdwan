'use strict';
'require view';
'require rpc';
'require ui';

var listCustomers = rpc.declare({object: 'knx.customer', method: 'list', expect: {'': {}}});
var controlCustomer = rpc.declare({object: 'knx.customer', method: 'control',
 params: ['customer', 'action', 'request_id'], expect: {'': {}}});
var updateMetadata = rpc.declare({object:'knx.customer', method:'update_metadata',
 params:['customer','name','notes','expected_revision'], expect:{'':{}}});

var labels = {on:'开启业务互联', off:'关闭业务互联', disconnect:'完全断开 VPN', reconnect:'恢复 VPN'};
var vpnLabels = {recent:'近期握手（在线参考）', stale:'握手陈旧，在线状态未知',
 unhandshaken:'尚未握手', disconnected:'已完全断开', missing:'已配置但运行时 Peer 缺失',
 mismatch:'配置与运行状态不一致', unknown:'状态未知'};

function bytes(n) {
 if (typeof n !== 'number') return '暂无可靠数据';
 var units=['B','KiB','MiB','GiB','TiB'], i=0;
 while (n>=1024 && i<units.length-1) { n/=1024; i++; }
 return n.toFixed(i ? 2 : 0)+' '+units[i];
}
function stamp(n) { return typeof n==='number' ? new Date(n*1000).toLocaleString() : '暂无记录'; }
function overview(c) {
 if (!c.status_ok || c.business_state==='UNKNOWN' || ['unknown','mismatch'].indexOf(c.vpn_state)>=0)
  return {label:'状态待确认',tone:'warn',hint:'请刷新状态，并展开详情核对。'};
 if (c.business_state==='DISCONNECT' && c.vpn_state==='disconnected')
  return {label:'VPN 已断开',tone:'muted',hint:'管理和业务均已断开；恢复 VPN 后业务默认关闭。'};
 if (c.vpn_state==='recent' && c.business_state==='ON')
  return {label:'在线 · 已互联',tone:'on',hint:'近期有 WG 握手，业务开关已开启；目标设备可达性仍需实际验证。'};
 if (c.vpn_state==='recent' && c.business_state==='OFF')
  return {label:'在线 · 未互联',tone:'ready',hint:'管理隧道近期有活动，业务互联已关闭。'};
 return {label:c.business_state==='ON'?'未联机 · 互联已开':'未联机',tone:'warn',hint:c.business_state==='ON'?'没有近期握手；业务开关仍开启，但实际通信未确认。':'没有近期握手，不能确认设备在线；不代表已主动断开 VPN。'};
}
function candidateText(c) {
 if (c.candidate_ready===true) return '可开启 · '+(c.candidate_subnet || '已识别真实网段');
 if (c.candidate_ready!==false) return '暂无可靠候选状态';
 var reason=c.candidate_reason || '';
 if (reason==='physical WAN has no active DHCP lease') return '等待客户网络（物理 WAN 无有效 DHCP）';
 if (reason==='candidate communication unavailable') return '候选查询暂不可用';
 if (reason.indexOf('overlap')>=0) return '存在网段冲突，暂不可开启';
 return '暂不可开启 · '+(reason || '尚未识别有效客户网络');
}

return view.extend({
 load: function() { return listCustomers(); },
 setBusy: function(busy) {
  this.busy=busy;
  this.root.querySelectorAll('button').forEach(function(b) {
   b.disabled=busy || (b.dataset.write==='yes' && this.readonly) || b.dataset.blocked==='yes';
  },this);
 },
 confirmDisconnect: function(c) {
  return new Promise(function(resolve) {
   ui.showModal('确认完全断开 VPN', [
    E('p',{},'将断开 '+c.name+' 的业务及 WG 管理通道。可在本页面点击“恢复 VPN”重新接入，恢复后业务默认关闭。'),
    E('div',{class:'right'},[
     E('button',{class:'btn',click:function(){ui.hideModal();resolve(false);}},'取消'),
     ' ', E('button',{class:'btn cbi-button-negative',click:function(){ui.hideModal();resolve(true);}},'确认断开')
    ])
   ]);
  });
 },
 refresh: function() {
  return listCustomers().then(function(data) {
   if (!data || data.success!==true) throw new Error('读取状态失败，请稍后刷新');
   this.draw(data);
  }.bind(this));
 },
 editMetadata: function(c) {
  if (this.busy || this.readonly) return;
  this.setBusy(true);
  var name=E('input',{type:'text',class:'cbi-input-text',maxlength:64,value:c.name || '',placeholder:'例如：王先生 · 城南项目'});
  var notes=E('textarea',{class:'cbi-input-textarea',rows:6,maxlength:2000,placeholder:'记录现场情况、联系人或维护注意事项（最多 2000 字）'},c.notes || '');
  var error=E('p',{class:'alert-message error',role:'alert',style:'display:none'});
  var cancel=E('button',{class:'btn',click:function(){ui.hideModal();this.setBusy(false);}.bind(this)},'取消');
  var save=E('button',{class:'btn cbi-button-positive',click:async function() {
   if (save.disabled) return;
   error.style.display='none';
   if (!name.value.trim()) {error.textContent='请填写客户名称';error.style.display='';name.focus();return;}
   save.disabled=true;cancel.disabled=true;save.classList.add('spinning');
   try {
    var result=await updateMetadata(c.id,name.value,notes.value,String(c.metadata_revision || 0));
    if (!result || !result.success) throw new Error(result && result.message || '保存失败，请稍后重试');
    ui.hideModal();
    try {await this.refresh();ui.addNotification(null,E('p',{},result.message),'info');}
    catch(e) {ui.addNotification(null,E('p',{},'资料已保存，但状态刷新失败，请点击“刷新状态”。'),'warning');}
    this.setBusy(false);
   } catch(e) {error.textContent=e.message || '保存失败，请稍后重试';error.style.display='';}
   finally {save.disabled=false;cancel.disabled=false;save.classList.remove('spinning');}
  }.bind(this)},'保存');
  ui.showModal('编辑客户名称与备注',[
   E('div',{class:'knx-metadata-editor'},[
    E('style',{},[
     '.knx-metadata-editor{display:grid;grid-template-columns:minmax(0,1fr);gap:16px;width:100%;box-sizing:border-box}',
     '.knx-metadata-editor .knx-edit-intro{margin:0;overflow-wrap:anywhere;opacity:.8}',
     '.knx-metadata-editor .knx-edit-field{display:grid;grid-template-columns:minmax(0,1fr);gap:6px;float:none;clear:both;width:100%;min-width:0;margin:0;padding:0;box-sizing:border-box}',
     '.knx-metadata-editor .knx-edit-label{display:block;float:none;clear:both;width:auto;max-width:100%;margin:0;padding:0;text-align:left;font-weight:500}',
     '.knx-metadata-editor input.cbi-input-text,.knx-metadata-editor textarea.cbi-input-textarea{display:block;float:none;width:100%;max-width:100%;min-width:0;margin:0;box-sizing:border-box;font:inherit;line-height:1.5;padding:9px 11px}',
     '.knx-metadata-editor textarea.cbi-input-textarea{height:160px;min-height:130px;max-height:50vh;resize:vertical}',
     '.knx-metadata-editor .knx-edit-actions{display:flex;justify-content:flex-end;align-items:center;gap:10px;float:none;clear:both;margin:0;padding:0}',
     '.knx-metadata-editor .alert-message{margin:0}',
     '@media(max-width:600px){.knx-metadata-editor input.cbi-input-text,.knx-metadata-editor textarea.cbi-input-textarea{font-size:16px}.knx-metadata-editor .knx-edit-actions .btn{min-height:44px}}'
    ].join('')),
    E('p',{class:'knx-edit-intro'},'仅修改显示资料，不改变客户 ID、VPN、路由或业务开关。'),
    E('div',{class:'knx-edit-field'},[E('label',{class:'knx-edit-label',for:'knx-edit-name'},'客户名称'),name]),
    E('div',{class:'knx-edit-field'},[E('label',{class:'knx-edit-label',for:'knx-edit-notes'},'备注 / 注意事项'),notes]),
    error,E('div',{class:'knx-edit-actions'},[cancel,save])
   ])
  ]);
  name.id='knx-edit-name';notes.id='knx-edit-notes';name.focus();
 },
 operate: async function(c, action, ev) {
  if (this.busy || this.readonly) return;
  this.setBusy(true);
  var button=ev.currentTarget;
  try {
   if (action==='disconnect' && !(await this.confirmDisconnect(c))) return;
   button.classList.add('spinning');
   var requestId=Date.now().toString(36)+'-'+Math.random().toString(36).slice(2)+'-'+Math.random().toString(36).slice(2);
   var result=await controlCustomer(c.id,action,requestId);
   try {await this.refresh();}
   catch(refreshError) {
    if (result && result.success===false) throw new Error((result.message || result.reason || '操作失败')+'（状态刷新也失败，请手动刷新。）');
    throw refreshError;
   }
   if (!result || result.success!==true) throw new Error(result && result.message || '操作失败，请刷新检查');
   ui.addNotification(null,E('p',{},labels[action]+'：'+result.message),'info');
  } catch(e) {
   ui.addNotification(null,E('p',{},e.message || '操作或状态读取失败，请刷新确认'),'danger');
  } finally { button.classList.remove('spinning'); this.setBusy(false); }
 },
 draw: function(data) {
  this.detailOpen=this.detailOpen || {};
  var cards=(data.customers || []).map(function(c) {
   var state=overview(c);
   var rows=[];
   function row(name,value) {rows.push(E('div',{class:'knx-row'},[E('strong',{},name),E('span',{},String(value==null?'未知':value))]));}
   row('设备型号',c.model);
   row('完整备注',c.notes || '暂无备注');
   row('WG 隧道 IP',c.tunnel_ip);
   row('Cudy 下挂 LAN',c.lan);
   row('客户真实网段',candidateText(c));
   if (c.candidate_ready===false) row('当前不可开启原因',c.current_rejection_reason || c.candidate_reason || 'No specific reason is available; refresh status.');
   row('VPN 配置 / 启用',(c.configured?'已配置':'未配置')+' / '+(c.enabled?'已启用':'已禁用'));
   row('VPN 状态',vpnLabels[c.vpn_state] || vpnLabels.unknown);
   row('最近握手',c.last_handshake ? stamp(c.last_handshake)+'（'+c.handshake_age+' 秒前）' : '无有效握手记录');
   row('业务状态',c.business_state);
   row('接收 / 发送',bytes(c.rx_bytes)+' / '+bytes(c.tx_bytes));
   var op=c.last_operation;
   row('最近操作',op ? stamp(op.timestamp)+' · '+(labels[op.action] || op.action)+' · '+(op.success?'成功':'失败')+' · '+op.message : '暂无网页操作记录');
   if (op && op.success===false) row('上次操作失败原因',op.reason || 'Older record has no saved reason; see current conditions above.');
   var buttons=Object.keys(labels).map(function(action) {
    var blocked=!c.control_enabled || (action==='on' && c.business_state==='DISCONNECT');
    return E('button',{class:'btn '+(action==='disconnect'?'cbi-button-negative':action==='on'?'cbi-button-positive':'cbi-button-neutral'),
     'data-write':'yes','data-blocked':blocked?'yes':'no',disabled:this.readonly || blocked,
     click:this.operate.bind(this,c,action)},labels[action]);
   },this);
   var details=E('details',{class:'knx-details',toggle:function(ev){this.detailOpen[c.id]=ev.currentTarget.open;}.bind(this)},[
    E('summary',{},'详细信息'),
    E('div',{class:'knx-detail-body'},[
     E('div',{class:'knx-detail-toolbar'},[
      E('button',{class:'btn knx-edit','data-write':'yes',disabled:this.readonly,click:this.editMetadata.bind(this,c)},'编辑名称与备注'),
      E('span',{class:'knx-note knx-model'},c.model || '')
     ]),
     E('p',{class:'knx-state-hint'},state.hint),
     E('div',{class:'knx-detail-rows'},rows),
     E('div',{class:'knx-buttons'},buttons),
     E('p',{class:'knx-note knx-footnote'},'在线状态依据近期 WG 握手，并非对客户目标设备的连通保证。流量是当前 Peer 计数，断开后可能清零。')
    ])
   ]);
   if (this.detailOpen[c.id]) details.open=true;
   return E('section',{class:'cbi-section knx-card'},[
    E('div',{class:'knx-card-head'},[
     E('h3',{class:'knx-title'},c.name || c.id),
     E('span',{class:'knx-badge knx-'+state.tone,role:'status',title:state.hint},state.label)
    ]),
    E('p',{class:'knx-note knx-note-preview'},c.notes || '暂无备注'),details
   ]);
  },this);
  this.cards.replaceChildren.apply(this.cards,cards.length?cards:[E('p',{},'未登记客户')]);
  this.updated.textContent='服务端状态读取时间：'+stamp(data.observed_at);
 },
 render: function(data) {
  this.readonly=!L.hasViewPermission();
  this.cards=E('div',{});
  this.updated=E('p',{class:'knx-note'});
  this.root=E('div',{class:'knx-maintenance'},[
   E('style',{},[
    '.knx-maintenance .knx-card{box-sizing:border-box;max-width:660px;padding:18px 22px 12px;margin:1rem auto;border-radius:10px;font-size:14px;line-height:1.5}',
    '.knx-maintenance .knx-card-head{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:14px}',
    '.knx-maintenance .knx-card .knx-card-head .knx-title{margin:0;padding:0;border:0;width:auto;min-width:0;font-size:17px;line-height:1.5;font-weight:600;overflow-wrap:anywhere}',
    '.knx-maintenance .knx-note{opacity:.75}',
    '.knx-maintenance .knx-note-preview{margin:10px 0 0;white-space:pre-wrap;overflow-wrap:anywhere;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}',
    '.knx-maintenance .knx-badge{display:inline-flex;align-items:center;border-radius:999px;padding:4px 10px;font-size:12px;font-weight:600;white-space:nowrap}',
    '.knx-maintenance .knx-badge:before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor;margin-right:6px;flex-shrink:0}',
    '.knx-maintenance .knx-on{background:#dff5e8;color:#135b35}.knx-maintenance .knx-ready{background:#e6edff;color:#254eaa}.knx-maintenance .knx-warn{background:#fff0cd;color:#784c00}.knx-maintenance .knx-muted{background:#e9ecef;color:#4d5660}',
    '.knx-maintenance .knx-details{margin-top:9px}.knx-maintenance .knx-details>summary{cursor:pointer;font-size:12px;font-weight:400;width:max-content;max-width:100%;margin-left:auto;padding:4px 0;opacity:.8}',
    '.knx-maintenance .knx-detail-body{margin-top:10px;padding-top:14px;border-top:1px solid rgba(128,128,128,.18)}',
    '.knx-maintenance .knx-detail-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:10px}',
    '.knx-maintenance .knx-edit{font-size:12px}.knx-maintenance .knx-model{font-size:12px}.knx-maintenance .knx-state-hint{font-size:12px;opacity:.75;margin:8px 0}',
    '.knx-maintenance .knx-row{display:grid;grid-template-columns:minmax(8rem,30%) minmax(0,1fr);gap:.5rem;padding:.4rem 0;border-bottom:1px solid rgba(128,128,128,.15)}.knx-maintenance .knx-row span{overflow-wrap:anywhere;white-space:pre-wrap}',
    '.knx-maintenance .knx-buttons{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;margin-top:14px}',
    '.knx-maintenance .knx-buttons .btn{box-sizing:border-box;display:inline-flex;align-items:center;justify-content:center;width:100%;min-width:0;float:none;margin:0;padding:9px 6px;font-size:12px;white-space:normal}',
    '.knx-maintenance .knx-footnote{font-size:12px;margin:10px 0 0}',
    '@media(max-width:480px){.knx-maintenance .knx-card{padding:16px 16px 10px}.knx-maintenance .knx-card .knx-card-head .knx-title{font-size:16px}.knx-maintenance .knx-badge{font-size:11px;padding:4px 8px}.knx-maintenance .knx-row{grid-template-columns:1fr;gap:.1rem}.knx-maintenance .knx-buttons{grid-template-columns:repeat(2,minmax(0,1fr))}.knx-maintenance .knx-buttons .btn,.knx-maintenance .knx-edit{min-height:44px}.knx-maintenance .knx-details>summary{min-height:36px;box-sizing:border-box;padding-top:8px}}'
   ].join('')),
   E('h2',{},'KNX 客户远程维护中心'),
   E('p',{class:'knx-note'},'业务关闭时仍保留管理隧道；恢复 VPN 后默认关闭业务。设备资料和详细状态可在下方卡片中查看。'),
   this.readonly?E('p',{class:'alert-message warning'},'当前账号只有读取权限，控制按钮已禁用。'):E('span'),
   E('button',{class:'btn cbi-button-action',click:async function(){
    if(this.busy)return;this.setBusy(true);
    try {await this.refresh();} catch(e) {ui.addNotification(null,E('p',{},e.message),'danger');}
    finally {this.setBusy(false);}
   }.bind(this)},'刷新状态'),this.updated,this.cards
  ]);
  if (!data || data.success!==true) ui.addNotification(null,E('p',{},'初始状态读取失败，请刷新重试'),'danger');
  this.draw(data || {});
  this.setBusy(false);
  return this.root;
 },
 handleSaveApply:null,handleSave:null,handleReset:null
});
