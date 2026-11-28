// Styles for the page's shadow root. Colours are the host's theme tokens, so
// light and dark follow the app; body swatches use cadkit's palette.
export const STYLE = `
:host,*{box-sizing:border-box}
.app{height:100%;min-height:0;display:flex;flex-direction:column;overflow:hidden;font:14px/1.45 system-ui,sans-serif;color:var(--foreground);background:var(--background)}
[hidden]{display:none!important}
button,select,input,textarea{font:inherit;color:inherit}
button{background:var(--background);border:1px solid var(--border);border-radius:6px;min-height:32px;padding:4px 10px;cursor:pointer}
button:hover:not(:disabled){background:var(--accent)}
button:disabled{opacity:.5;cursor:default}
button.primary{background:var(--primary);color:var(--primary-foreground);border-color:var(--primary)}
button.primary:hover:not(:disabled){background:color-mix(in oklch,var(--primary) 85%,var(--background))}
button[aria-pressed=true],button[aria-selected=true]{background:var(--accent);border-color:var(--ring)}
:focus-visible{outline:2px solid var(--ring);outline-offset:-2px}
select,input[type=text],textarea{background:var(--background);border:1px solid var(--border);border-radius:6px;padding:4px 8px}
a{color:var(--primary)}
.bar{display:flex;align-items:center;gap:8px;padding:8px 12px;border-bottom:1px solid var(--border);min-height:52px;flex-wrap:wrap}
.bar h1{font-size:16px;font-weight:600;margin:0;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.grow{flex:1}
.muted{color:var(--muted-foreground)}
.error{color:var(--destructive)}
.pad{padding:12px}
.notice{padding:6px 12px;border-bottom:1px solid var(--border);background:color-mix(in oklch,var(--destructive) 10%,var(--background));overflow-wrap:anywhere}
.notice.info{background:color-mix(in oklch,var(--accent) 60%,var(--background))}
.banner{display:flex;flex-direction:column;align-items:flex-start;gap:4px}
.banner p{margin:0}
.banner pre{margin:0;max-width:100%;padding:6px 8px;border:1px solid var(--border);border-radius:6px;background:var(--background);overflow-x:auto;font:12px/1.5 ui-monospace,monospace}
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
.msg.tool summary{font-size:12px;color:var(--muted-foreground);cursor:pointer}
.msg.tool pre{margin:4px 0 0;padding:6px 8px;border:1px solid var(--border);border-radius:6px;max-height:16rem;overflow:auto;white-space:pre-wrap;font:12px/1.45 ui-monospace,monospace}
.chip{display:inline-block;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px;border:1px solid var(--border);border-radius:999px;padding:1px 8px;margin:4px 4px 0 0;color:var(--muted-foreground)}
.chip.done{border-color:var(--ring)}
.working{font-size:12px;color:var(--muted-foreground)}
.composer{border-top:1px solid var(--border);padding:8px;display:flex;flex-direction:column;gap:6px}
.composer .viewing{font-size:12px}
.composer textarea{width:100%;min-height:64px;max-height:40vh;resize:vertical}
.composer .row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.composer .run-controls{display:flex;align-items:center;min-width:0;flex:0 1 auto}
.divider{cursor:col-resize;background:transparent;border:0;border-radius:0;padding:0;min-height:0}
.divider:hover,.divider:focus-visible{background:var(--border)}
.work{min-width:0;min-height:0;display:flex;flex-direction:column}
.tabs{display:flex;gap:8px;padding:6px 8px;border-bottom:1px solid var(--border);flex-wrap:wrap;align-items:center}
.tablist{display:flex;gap:4px;flex-wrap:wrap}
.version{display:flex;gap:6px;align-items:center}
.phone-tabs button{position:relative}
.dot{position:absolute;top:3px;right:3px;width:7px;height:7px;border-radius:50%;background:var(--primary)}
.panel{flex:1;min-height:0;display:none;flex-direction:column;overflow:auto}
.work[data-tab=preview] .panel.preview,.work[data-tab=views] .panel.views,.work[data-tab=checks] .panel.checks,.work[data-tab=code] .panel.code,.work[data-tab=files] .panel.files{display:flex}
.panel.preview{overflow:hidden}
.toolbar{display:flex;gap:6px;padding:6px 8px;align-items:center;flex-wrap:wrap;border-bottom:1px solid var(--border)}
.stage{flex:1;min-height:0;display:flex}
.viewport{position:relative;flex:1;min-width:0;min-height:160px;overflow:hidden}
.viewport canvas{position:absolute;inset:0;width:100%;height:100%;display:block}
.overlay{position:absolute;left:8px;top:8px;max-width:calc(100% - 16px);padding:4px 8px;border:1px solid var(--border);border-radius:6px;background:color-mix(in oklch,var(--background) 88%,transparent);overflow-wrap:anywhere;pointer-events:none}
.overlay.error{border-color:var(--destructive)}
.placeholder{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--muted-foreground);padding:24px;text-align:center}
.bodies{list-style:none;margin:0;padding:8px;width:min(15rem,40%);overflow:auto;border-left:1px solid var(--border);display:flex;flex-direction:column;gap:8px}
.body label{display:flex;align-items:center;gap:6px;min-width:0}
.body .name{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.body .meta{display:block;font-size:12px;color:var(--muted-foreground);padding-left:22px;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}
.body .meta.error{color:var(--destructive)}
.swatch{width:12px;height:12px;border-radius:3px;flex:none;border:1px solid var(--border)}
.info{padding:6px 10px;border-top:1px solid var(--border);font-variant-numeric:tabular-nums;display:flex;gap:12px;flex-wrap:wrap}
.gallery{display:grid;gap:12px;padding:12px;grid-template-columns:repeat(auto-fill,minmax(min(100%,320px),1fr))}
.gallery figure{margin:0;display:flex;flex-direction:column;gap:4px}
.gallery img{width:100%;height:auto;border:1px solid var(--border);border-radius:6px;background:#fff}
.gallery figcaption{font-size:12px;color:var(--muted-foreground)}
.check{padding:8px 12px;border-bottom:1px solid var(--border);overflow-wrap:anywhere}
.check h3{font-size:14px;margin:0 0 4px}
.check p{margin:4px 0}
.check ul{margin:4px 0;padding-left:18px}
.source{flex:1;margin:0;padding:10px 12px;overflow:auto;white-space:pre;font:12px/1.5 ui-monospace,monospace;tab-size:4}
.file-list{list-style:none;margin:0;padding:8px 12px;display:flex;flex-direction:column;gap:6px}
.file-list li{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;overflow-wrap:anywhere}
.phone-tabs{display:none}
/* phone: one pane at a time */
.app.narrow .split{display:flex;flex-direction:column}
.app.narrow .divider{display:none}
.app.narrow .phone-tabs{display:flex;gap:4px;padding:6px 8px;border-bottom:1px solid var(--border)}
.app.narrow .phone-tabs button{flex:1;min-height:44px}
.app.narrow .chat{border-right:0;flex:1}
.app.narrow .work{flex:1}
.app.narrow[data-phone=prompt] .work,.app.narrow:not([data-phone=prompt]) .chat{display:none}
.app.narrow .stage{flex-direction:column}
.app.narrow .bodies{width:auto;max-height:30%;border-left:0;border-top:1px solid var(--border)}
.app.narrow button{min-height:40px}
@media (pointer:coarse){button{min-height:44px}}
`;
