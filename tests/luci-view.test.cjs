// Offline UI logic test only: no browser, credentials or router requests.
const fs=require('fs'),assert=require('assert');
class Element {
 constructor(tag,attrs={},children=[]) {
  this.tag=tag;this.attrs=attrs;this.children=[];this.dataset={};this.style={};this.disabled=!!attrs.disabled;this.open=false;this.value=attrs.value || '';this.id=attrs.id;
  this.classList={add(){},remove(){}};
  for(const [k,v]of Object.entries(attrs)) {if(k.startsWith('data-'))this.dataset[k.slice(5)]=v;if(typeof v==='function')this[k]=v;}
  this.replaceChildren(...(Array.isArray(children)?children:[children]));
  if(tag==='textarea')this.value=this.textContent;
 }
 replaceChildren(...children){this.children=children.filter(x=>x!==undefined && x!==null);}
 get textContent(){return this.children.map(c=>c instanceof Element?c.textContent:String(c)).join('');}
 set textContent(value){this.children=[String(value)];}
 querySelectorAll(tag){return this.children.flatMap(c=>c instanceof Element?[...(c.tag===tag?[c]:[]),...c.querySelectorAll(tag)]:[]);}
 focus(){this.focused=true;}
}
const E=(tag,attrs,children)=>new Element(tag,attrs,children);
let metadataCalls=0,controlCalls=0,modal=null,notifications=[];
let controlReply=null,listFails=false;
let customer={id:'a',name:'客户 A',notes:'原备注',metadata_revision:0,model:'Cudy TR3000 v1',tunnel_ip:'10.62.0.11',lan:'10.61.1.0/24',status_ok:true,configured:true,enabled:true,control_enabled:true,vpn_state:'recent',business_state:'OFF',handshake_age:12};
const data=()=>({success:true,customers:[{...customer}],observed_at:1700000000});
const rpc={declare(opts){
 if(opts.method==='list')return async()=>{if(listFails)throw Error('simulated status refresh failure');return data();};
 if(opts.method==='control')return async()=>{controlCalls++;if(controlReply)return controlReply;throw Error('must not control VPN in this test');};
 if(opts.method==='update_metadata')return async(id,name,notes,revision)=>{metadataCalls++;assert.equal(typeof revision,'string');assert.equal(revision,String(customer.metadata_revision));await Promise.resolve();customer={...customer,name,notes,metadata_revision:customer.metadata_revision+1};return {success:true,message:'已保存'};};
 throw Error('unexpected RPC');
}};
const ui={showModal(title,children){modal=E('div',{},children);},hideModal(){modal=null;},addNotification(a,b,t){notifications.push({type:t,text:b.textContent});}};
const definition=new Function('view','rpc','ui','L','E',fs.readFileSync(require('path').join(__dirname,'../src/r86s/www/luci-static/resources/view/knx/maintenance.js'),'utf8'))({extend:x=>x},rpc,ui,{hasViewPermission:()=>true},E);
const view={...definition};view.render(data());
assert(view.root.textContent.includes('在线 · 未互联'));assert(!view.root.querySelectorAll('details')[0].open);
const card=view.cards.children[0],detail=card.querySelectorAll('details')[0];
assert.equal(card.children.length,3,'collapsed card has only header, notes and details');
assert(card.children[0].textContent.includes('客户 A') && card.children[0].textContent.includes('在线 · 未互联'));
assert.equal(card.querySelectorAll('button').length,5);assert.equal(detail.querySelectorAll('button').length,5,'all edit and control buttons must be inside details');
for(const [vpn,biz,label]of [['recent','ON','在线 · 已互联'],['stale','OFF','未联机'],['disconnected','DISCONNECT','VPN 已断开'],['unknown','UNKNOWN','状态待确认']]){
 customer={...customer,vpn_state:vpn,business_state:biz};view.draw(data());assert(view.root.textContent.includes(label));
}
customer={...customer,vpn_state:'recent',business_state:'OFF'};view.draw(data());
(async()=>{
 let details=view.root.querySelectorAll('details')[0];details.open=true;details.toggle({currentTarget:details});await view.refresh();assert(view.root.querySelectorAll('details')[0].open);
 view.editMetadata(customer);assert(modal && view.busy);
 const editor=modal.children[0];assert.equal(editor.attrs.class,'knx-metadata-editor');
 const fields=editor.children.filter(e=>e instanceof Element && e.attrs.class==='knx-edit-field');
 assert.equal(fields.length,2);assert.equal(fields[0].children[0].tag,'label');assert.equal(fields[0].children[1].tag,'input');assert.equal(fields[1].children[0].tag,'label');assert.equal(fields[1].children[1].tag,'textarea');
 assert(!editor.querySelectorAll('div').some(e=>['cbi-value','cbi-value-field'].includes(e.attrs.class)),'modal must not inherit the LuCI two-column form layout');
 let name=modal.querySelectorAll('input')[0],notes=modal.querySelectorAll('textarea')[0];
 let save=modal.querySelectorAll('button').find(b=>b.textContent==='保存');
 name.value='';await save.click();assert.equal(metadataCalls,0);assert(modal.textContent.includes('请填写客户名称'));
 name.value='示例客户 · 测试站点';notes.value='第一行注意事项\n第二行 ✅ <b>普通文字</b>';
 await Promise.all([save.click(),save.click()]);assert.equal(metadataCalls,1);assert.equal(controlCalls,0);assert(!modal && !view.busy);assert(view.root.textContent.includes('示例客户 · 测试站点'));assert(view.root.textContent.includes('第二行 ✅ <b>普通文字</b>'));
 view.readonly=true;view.setBusy(false);view.editMetadata(customer);assert(!modal);assert(view.root.querySelectorAll('button').filter(b=>b.dataset.write==='yes').every(b=>b.disabled));
 view.readonly=false;view.setBusy(false);
 const reason='physical WAN has no active DHCP lease';
 customer={...customer,candidate_ready:false,current_rejection_reason:reason,last_operation:{timestamp:1700000000,action:'on',success:false,message:'操作被拒绝或失败：'+reason,reason}};
 view.draw(data());assert(view.root.textContent.includes('当前不可开启原因'));assert(view.root.textContent.includes('上次操作失败原因'));assert(view.root.textContent.includes(reason));
 controlReply={success:false,message:'操作被拒绝或失败：'+reason,reason};
 await view.operate(customer,'on',{currentTarget:view.root.querySelectorAll('button').find(b=>b.textContent==='开启业务互联')});
 assert(notifications.at(-1).text.includes(reason));assert(!view.busy);
 listFails=true;
 await view.operate(customer,'on',{currentTarget:view.root.querySelectorAll('button').find(b=>b.textContent==='开启业务互联')});
 assert(notifications.at(-1).text.includes(reason));assert(notifications.at(-1).text.includes('刷新也失败'));assert(!view.busy);
 console.log('PASS: compact layout, metadata editor, readonly, rejection details and toast, cause survives refresh failure; offline simulated RPC only');
})().catch(e=>{console.error(e);process.exitCode=1;});
