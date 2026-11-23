// Styles for the page's shadow root. Colours are the host's theme tokens, so
// light and dark follow the app; the code colours are mixed from them.
export const STYLE = `
:host,*{box-sizing:border-box}
.app{--cad-keyword:var(--primary,#6d28d9);--cad-string:color-mix(in oklch,var(--foreground) 35%,#15803d);--cad-number:color-mix(in oklch,var(--foreground) 35%,#c2410c);--cad-atom:color-mix(in oklch,var(--foreground) 35%,#0e7490);--cad-builtin:color-mix(in oklch,var(--foreground) 30%,#1d4ed8);
  height:100%;min-height:0;display:flex;flex-direction:column;overflow:hidden;font:14px/1.45 system-ui,sans-serif;color:var(--foreground);background:var(--background)}
[hidden]{display:none!important}
button,select,input,textarea{font:inherit;color:inherit}
button{background:var(--background);border:1px solid var(--border);border-radius:6px;min-height:32px;padding:4px 10px;cursor:pointer}
button:hover:not(:disabled){background:var(--accent)}
button:disabled{opacity:.5;cursor:default}
button.primary{background:var(--primary);color:var(--primary-foreground);border-color:var(--primary)}
button.primary:hover:not(:disabled){background:color-mix(in oklch,var(--primary) 85%,var(--background))}
button.link{border:0;background:none;padding:0 2px;min-height:0;text-decoration:underline;color:inherit}
button[aria-pressed=true],button[aria-selected=true]{background:var(--accent);border-color:var(--ring)}
:focus-visible{outline:2px solid var(--ring);outline-offset:-2px}
select,input[type=text],textarea{background:var(--background);border:1px solid var(--border);border-radius:6px;padding:4px 8px}
.bar{display:flex;align-items:center;gap:8px;padding:8px 12px;border-bottom:1px solid var(--border);min-height:52px;flex-wrap:wrap}
.bar h1{font-size:16px;font-weight:600;margin:0;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.grow{flex:1}
.muted{color:var(--muted-foreground)}
.notice{padding:6px 12px;border-bottom:1px solid var(--border);background:color-mix(in oklch,var(--destructive) 10%,var(--background));overflow-wrap:anywhere}
.notice.info{background:color-mix(in oklch,var(--accent) 60%,var(--background))}
/* list */
.list{flex:1;overflow:auto;padding:16px;display:grid;gap:10px;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));align-content:start;margin:0;list-style:none}
.card{border:1px solid var(--border);border-radius:10px;padding:12px;display:flex;flex-direction:column;gap:8px;min-width:0}
.card .open{all:unset;cursor:pointer;display:flex;flex-direction:column;gap:2px;min-width:0;border-radius:6px}
.card .open:focus-visible{outline:2px solid var(--ring)}
.card .name{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.card .meta{font-size:12px;color:var(--muted-foreground)}
.card .actions{display:flex;gap:6px;flex-wrap:wrap}
.empty{padding:32px 16px;text-align:center;color:var(--muted-foreground)}
/* design */
.design{flex:1;min-height:0;display:flex;flex-direction:column}
.split{flex:1;min-height:0;display:grid;grid-template-columns:minmax(240px,var(--left,38%)) 6px minmax(0,1fr)}
.chat{min-width:0;min-height:0;display:flex;flex-direction:column;border-right:1px solid var(--border)}
.messages{flex:1;overflow:auto;padding:12px;display:flex;flex-direction:column;gap:10px}
.messages>.history,.messages>.live{display:flex;flex-direction:column;gap:10px}
.messages>.history:empty,.messages>.live:empty{display:none}
.msg{max-width:100%;overflow-wrap:anywhere}
.msg .who{font-size:12px;color:var(--muted-foreground);margin-bottom:2px}
.msg .text{white-space:pre-wrap}
.msg.user .text{background:var(--accent);border-radius:10px;padding:6px 10px;display:inline-block}
.chip{display:inline-block;font-size:12px;border:1px solid var(--border);border-radius:999px;padding:1px 8px;margin:4px 4px 0 0;color:var(--muted-foreground)}
.working{font-size:12px;color:var(--muted-foreground)}
.composer{border-top:1px solid var(--border);padding:8px;display:flex;flex-direction:column;gap:6px}
.composer textarea{width:100%;min-height:64px;max-height:40vh;resize:vertical}
.composer .row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.composer select{max-width:14rem}
.divider{cursor:col-resize;background:transparent;border:0;border-radius:0;padding:0;min-height:0}
.divider:hover,.divider:focus-visible{background:var(--border)}
.work{min-width:0;min-height:0;display:flex;flex-direction:column}
.tabs{display:flex;gap:4px;padding:6px 8px;border-bottom:1px solid var(--border);flex-wrap:wrap}
.tabs button{position:relative}
.dot{position:absolute;top:3px;right:3px;width:7px;height:7px;border-radius:50%;background:var(--primary)}
.panel{flex:1;min-height:0;display:none;flex-direction:column}
.work[data-tab=preview] .panel.preview,.work[data-tab=code] .panel.code,.work[data-tab=parameters] .panel.parameters,.work[data-tab=versions] .panel.versions{display:flex}
.toolbar{display:flex;gap:6px;padding:6px 8px;align-items:center;flex-wrap:wrap;border-bottom:1px solid var(--border)}
.viewport{position:relative;flex:1;min-height:160px;overflow:hidden}
.viewport canvas{position:absolute;inset:0;width:100%;height:100%;display:block}
.overlay{position:absolute;left:8px;top:8px;max-width:calc(100% - 16px);padding:4px 8px;border:1px solid var(--border);border-radius:6px;background:color-mix(in oklch,var(--background) 88%,transparent);overflow-wrap:anywhere;pointer-events:none}
.overlay.error{border-color:var(--destructive)}
.placeholder{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--muted-foreground);padding:24px;text-align:center}
.info{padding:6px 10px;border-top:1px solid var(--border);font-variant-numeric:tabular-nums;display:flex;gap:12px;flex-wrap:wrap}
.final{border-top:1px solid var(--border);padding:8px 10px;display:flex;flex-direction:column;gap:6px;max-height:40%;overflow:auto}
.final.mismatch .state,.final.failed .state{color:var(--destructive)}
.final ul{margin:0;padding-left:18px}
.editor{flex:1;min-height:0;overflow:hidden}
.held{padding:6px 10px;background:var(--accent);border-bottom:1px solid var(--border)}
.codebar{display:flex;gap:8px;align-items:center;padding:6px 8px;border-top:1px solid var(--border);flex-wrap:wrap}
.errors{padding:6px 10px;border-top:1px solid var(--border);color:var(--destructive);overflow-wrap:anywhere;max-height:30%;overflow:auto}
.params{flex:1;overflow:auto;padding:10px 12px;display:flex;flex-direction:column;gap:12px}
.param label{display:flex;justify-content:space-between;gap:8px;font-variant-numeric:tabular-nums}
.param input[type=range]{width:100%}
.param .range{font-size:12px;color:var(--muted-foreground)}
.versions ol{list-style:none;margin:0;padding:8px;overflow:auto;flex:1;display:flex;flex-direction:column;gap:4px}
.versions li button{width:100%;text-align:left;display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.versions .seq{font-weight:600;font-variant-numeric:tabular-nums}
.versions .error{color:var(--destructive)}
.versions .branch{font-size:12px;color:var(--muted-foreground)}
.phone-tabs{display:none}
/* phone: one pane at a time, parameters inside Code */
.app.narrow .split{display:flex;flex-direction:column}
.app.narrow .divider,.app.narrow .work>.tabs{display:none}
.app.narrow .phone-tabs{display:flex;gap:4px;padding:6px 8px;border-bottom:1px solid var(--border)}
.app.narrow .phone-tabs button{flex:1;position:relative;min-height:44px}
.app.narrow .chat{border-right:0;flex:1}
.app.narrow .work{flex:1}
.app.narrow[data-phone=prompt] .work,.app.narrow:not([data-phone=prompt]) .chat{display:none}
.app.narrow[data-phone=code] .panel.parameters{display:flex;flex:0 1 auto;max-height:45%;border-top:1px solid var(--border)}
.app.narrow button{min-height:40px}
@media (pointer:coarse){button{min-height:44px}}
`;
