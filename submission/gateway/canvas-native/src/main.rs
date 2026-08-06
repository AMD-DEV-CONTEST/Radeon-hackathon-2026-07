use eframe::egui::{self, *};
use std::env;
use std::fs;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use serde::Deserialize;

const DEFAULT_ORCHESTRATOR_URL: &str = "http://111.228.42.18:8000";

#[derive(Debug, Clone, Deserialize)]
struct AgData { name: Option<String>, agent_type: Option<String>, status: Option<String>, os: Option<String>, }
#[derive(Debug, Clone, Deserialize)]
struct TkData { id: String, title: Option<String>, status: Option<String>, }
struct Shared { ok: bool, agents: Vec<AgData>, tasks: Vec<TkData>, fetch_ms: u64 }

fn orchestrator_url() -> String {
    env::var("UAS_ORCHESTRATOR_URL").ok().filter(|v|!v.trim().is_empty())
        .unwrap_or_else(|| DEFAULT_ORCHESTRATOR_URL.to_string()).trim_end_matches('/').to_string()
}
fn fetch_data(base_url: &str) -> Shared {
    let t0=Instant::now(); let client=reqwest::blocking::Client::builder().timeout(Duration::from_secs(8)).build().unwrap_or_default();
    let agents=client.get(format!("{base_url}/agents")).send().and_then(|r|r.json::<Vec<AgData>>()).unwrap_or_default();
    let tasks=client.get(format!("{base_url}/tasks")).send().and_then(|r|r.json::<Vec<TkData>>()).unwrap_or_default();
    let ok = !agents.is_empty() || !tasks.is_empty();
    Shared{ok, agents, tasks, fetch_ms:t0.elapsed().as_millis() as u64}
}

const D_BG:  Color32 = Color32::from_rgb(10,12,16);
const D_PN:  Color32 = Color32::from_rgb(16,20,26);
const D_CD:  Color32 = Color32::from_rgb(22,28,36);
const D_BD:  Color32 = Color32::from_rgb(36,42,52);
const D_TX:  Color32 = Color32::from_rgb(220,226,236);
const D_TX2: Color32 = Color32::from_rgb(120,128,140);
const D_AC:  Color32 = Color32::from_rgb(56,189,248);
const D_GN:  Color32 = Color32::from_rgb(74,222,128);
const D_AM:  Color32 = Color32::from_rgb(251,191,36);
const D_RD:  Color32 = Color32::from_rgb(248,113,113);

fn sc(s: &str) -> Color32 { match s {"online"|"done"=>D_GN,"busy"|"doing"=>D_AM,"queued"=>D_TX2,_=>D_RD} }

struct UasCanvas { start: Instant, shared: Arc<Mutex<Shared>>, dorm_open: bool, tasks_open: bool, sel: usize, msgs: Vec<(String,String)>, dark: bool }
impl UasCanvas {
    fn new(s: Arc<Mutex<Shared>>)->Self{ Self{start:Instant::now(),shared:s,dorm_open:true,tasks_open:true,sel:0,
        dark:true, msgs:vec![
            ("二弟".into(),"v0.6.0: Dark Mode 科技风指挥舱，双模式切换审查。".into()),
            ("二弟".into(),"安全: 只读 REST / 无 token / 无 CoT / 不连 Gateway。".into()),
        ]}
    }
    fn up(&self)->String{let s=self.start.elapsed().as_secs();format!("{:02}:{:02}",s/3600,(s%3600)/60)}
}

fn card(ui:&mut Ui,c:Color32,f:impl FnOnce(&mut Ui)){
    Frame::default().fill(c).stroke(Stroke::new(1.0,D_BD)).corner_radius(10).inner_margin(12.0)
        .shadow(Shadow{offset:[0,4].into(),blur:16,spread:0,color:Color32::from_black_alpha(40)}).show(ui,f);
}
fn chdr(ui:&mut Ui,open:&mut bool,icon:&str,title:&str,hint:&str){
    let chev=if *open{"▾"}else{"▸"};
    let r=ui.add(Label::new(RichText::new(format!("{icon} {title}   {chev} {hint}")).size(12.0).color(D_TX2)).sense(Sense::click()));
    if r.clicked(){*open=!*open;} ui.add_space(3.0);
}

fn configure_fonts(ctx: &Context) {
    let candidates = [
        r"C:\Windows\Fonts\NotoSansSC-VF.ttf",
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
    ];
    for path in candidates {
        if let Ok(bytes) = fs::read(path) {
            let mut fonts = FontDefinitions::default();
            fonts.font_data.insert("uas_zh".to_owned(), FontData::from_owned(bytes).into());
            fonts.families.entry(FontFamily::Proportional).or_default().insert(0, "uas_zh".to_owned());
            fonts.families.entry(FontFamily::Monospace).or_default().insert(0, "uas_zh".to_owned());
            ctx.set_fonts(fonts);
            break;
        }
    }
}

impl eframe::App for UasCanvas {
    fn update(&mut self, ctx: &Context, _frame: &mut eframe::Frame) {
        let mut s=(*ctx.style()).clone(); s.visuals.dark_mode=self.dark;
        s.visuals.panel_fill=D_BG; s.visuals.window_fill=D_BG;
        s.visuals.override_text_color=Some(D_TX);
        s.visuals.widgets.inactive.bg_fill=D_CD;
        s.visuals.widgets.hovered.bg_fill=Color32::from_rgba_premultiplied(56,189,248,20);
        s.visuals.selection.bg_fill=Color32::from_rgba_premultiplied(56,189,248,30);
        s.spacing.item_spacing=[10.0,8.0].into(); ctx.set_style(s);

        let sh=self.shared.lock().unwrap();
        let online=sh.agents.iter().filter(|a|a.status.as_deref()==Some("online")).count();
        let fs_ok_val = sh.ok;
        let fs_ms_val = sh.fetch_ms;
        let agents_clone: Vec<(String,String,String,String)> = sh.agents.iter().map(|a|(a.name.clone().unwrap_or_default(),a.agent_type.clone().unwrap_or_default(),a.status.clone().unwrap_or_default(),a.os.clone().unwrap_or("?".into()))).collect();
        let tasks_clone: Vec<(String,String)> = sh.tasks.iter().map(|t|(t.title.clone().unwrap_or_default(),t.status.clone().unwrap_or_default())).collect();
        let task_ids: Vec<String> = sh.tasks.iter().map(|t|t.id.chars().take(12).collect()).collect();
        let agents_len = sh.agents.len();
        let tasks_len = sh.tasks.len();
        let queued_count = sh.tasks.iter().filter(|t|t.status.as_deref()==Some("queued")).count();
        let done_count = sh.tasks.iter().filter(|t|t.status.as_deref()==Some("done")).count();
        drop(sh);
        let fs_ok = fs_ok_val; let fs_ms = fs_ms_val;

        TopBottomPanel::top("tb").height_range(44.0..=50.0)
            .frame(Frame::default().fill(D_PN).inner_margin(Margin::symmetric(18,0)))
            .show(ctx,|ui|{ui.horizontal(|ui|{
                ui.label(RichText::new("UAS CANVAS").color(D_AC).size(15.0).strong());
                ui.label(RichText::new("明线指挥舱").color(D_TX2).size(12.0));
                ui.add_space(10.0);
                ui.label(RichText::new(format!("agents:{} online:{}",agents_len,online)).size(11.0).color(D_TX2));
                ui.with_layout(Layout::right_to_left(Align::Center),|ui|{
                    if ui.small_button(if self.dark{"light"}else{"dark"}).clicked(){self.dark=!self.dark;}
                    ui.add_space(8.0);
                    ui.label(RichText::new(format!("OP:{}",if fs_ok{format!("{}ms",fs_ms)}else{"off".into()})).color(if fs_ok{D_GN}else{D_RD}).size(10.0));
                    ui.label(RichText::new(format!("{}",self.up())).color(D_TX2).size(11.0));
                });
            });});

        if self.dorm_open {
            SidePanel::left("dorm").resizable(false).min_width(220.0).default_width(230.0)
                .frame(Frame::default().fill(D_BG).inner_margin(10.0))
                .show(ctx,|ui|{
                    ui.horizontal(|ui|{
                        ui.label(RichText::new("Dorm Standby").color(D_AM).size(13.0).strong());
                        ui.with_layout(Layout::right_to_left(Align::Center),|ui|{if ui.small_button("-").clicked(){self.dorm_open=false;}});
                    });ui.add_space(6.0);
                    ScrollArea::vertical().show(ui,|ui|{
                        for (i,(name,tp,st,os)) in agents_clone.iter().enumerate(){
                            let sel=i==self.sel;let bd=if sel{Stroke::new(2.0,D_AC)}else{Stroke::new(1.0,D_BD)};
                            let bg=if sel{Color32::from_rgba_premultiplied(56,189,248,10)}else{D_CD};
                            Frame::default().fill(bg).stroke(bd).corner_radius(8).inner_margin(10.0).show(ui,|ui|{
                                ui.horizontal(|ui|{ui.label(RichText::new("·").color(sc(st)).size(14.0));ui.label(RichText::new(name.as_str()).size(14.0).strong());});
                                if ui.interact(ui.max_rect(),Id::new(format!("a{}",i)),Sense::click()).clicked(){self.sel=i;}
                                ui.label(RichText::new(format!("{}  {}  {}",tp,os,st)).size(10.0).color(D_TX2));
                            });ui.add_space(3.0);
                        }
                    });
                });
        } else {
            SidePanel::left("dorm_cl").resizable(false).default_width(36.0).min_width(36.0).show(ctx,|ui|{ui.vertical_centered(|ui|{
                if ui.add(Button::new(RichText::new("+").color(D_AC).size(16.0)).fill(D_BG).frame(false)).clicked(){self.dorm_open=true;}
                for (_,_,st,_) in &agents_clone{ui.label(RichText::new("·").color(sc(st)).size(7.0));}
            });});
        }

        SidePanel::right("rp").resizable(false).min_width(280.0).default_width(290.0)
            .frame(Frame::default().fill(D_BG).inner_margin(10.0))
            .show(ctx,|ui|{
                chdr(ui,&mut self.tasks_open,"T","Task Flow",&format!("{}Q {}D",queued_count,done_count));
                if self.tasks_open{ScrollArea::vertical().show(ui,|ui|{
                    for (i,(title,st)) in tasks_clone.iter().enumerate(){
                        let c=sc(st);let ic=match st.as_str(){"done"=>"v","running"=>"*","queued"=>"-",_=>"x"};
                        let id0 = if i < task_ids.len() {&task_ids[i]} else {"?"};
                        Frame::default().fill(D_CD).stroke(Stroke::new(1.0,D_BD)).corner_radius(8).inner_margin(8.0).show(ui,|ui|{
                            ui.label(RichText::new(format!("{} {}",ic,title)).size(12.0).color(c));
                            ui.label(RichText::new(format!("{} {}",st,id0)).size(9.0).color(D_TX2));
                        });ui.add_space(3.0);
                    }
                });}
                ui.add_space(8.0);
                chdr(ui,&mut self.tasks_open,"!","Blockers","2");
                if self.tasks_open {
                    for (t,det,color) in [
                        ("SCC dark line locked","TCC system building - light line separated",D_RD),
                        ("roster_key unresolved","agent data-contract v2 pending",D_AM),
                    ] {
                        Frame::default().fill(D_CD).stroke(Stroke::new(1.0,color.gamma_multiply(0.2))).corner_radius(8).inner_margin(8.0).show(ui,|ui|{
                            ui.label(RichText::new(t).size(11.0).color(color).strong());
                            ui.label(RichText::new(det).size(10.0).color(D_TX2));
                        });ui.add_space(3.0);
                    }
                }
                ui.add_space(8.0);
                chdr(ui,&mut self.tasks_open,"@","Cockpit","ds-v4-pro");
                if self.tasks_open{
                    card(ui,D_CD,|ui|{
                        ui.label(RichText::new("deepseek-pro").size(13.0).strong());
                        ui.label(RichText::new("deepseek-v4-pro").size(10.0).color(D_TX2));
                        ui.add_space(3.0);
                        ui.add(ProgressBar::new(0.62).desired_width(ui.available_width()).show_percentage());
                        ui.colored_label(D_TX2,"context 620k / 1M tokens");
                        ui.add_space(3.0);
                        ui.horizontal(|ui|{ui.label(RichText::new("99.82% cache-hit").color(D_GN).size(11.0));
                            ui.with_layout(Layout::right_to_left(Align::Center),|ui|{ui.label(RichText::new("~0.3y/turn").color(D_TX2).size(10.0));});});
                        ui.separator();
                        ui.horizontal(|ui|{ui.colored_label(D_TX2,"planner: ");ui.label(RichText::new("mimo-v2.5-pro").size(11.0));});
                    });
                }
            });

        CentralPanel::default().frame(Frame::default().fill(D_BG).inner_margin(14.0)).show(ctx,|ui|{
            ui.horizontal(|ui|{
                ui.label(RichText::new("Meeting Room").color(D_GN).size(15.0).strong());
                ui.with_layout(Layout::right_to_left(Align::Center),|ui|{ui.label(RichText::new("UAS Canvas v0.6.0 dual-mode review").color(D_TX2).size(11.0));});
            });ui.add_space(6.0);
            ScrollArea::vertical().max_height(300.0).show(ui,|ui|{
                for (sp,tx) in &self.msgs{ui.horizontal(|ui|{ui.colored_label(D_AC,sp);ui.label(RichText::new(tx).size(11.0));});ui.add_space(2.0);}
            });
            ui.add_space(12.0);
            ui.colored_label(D_AM,RichText::new("Reasoning Summary").size(14.0).strong());
            ui.add_space(6.0);
            card(ui,D_PN,|ui|{
                ui.colored_label(D_TX2,"[Safety] Read-only Orchestrator REST. No token. No CoT. No Gateway. No SCC/TCC.");
                ui.add_space(6.0);
                ui.colored_label(D_GN,"Direction A (default): Dark Mode tech-style. High contrast. Cyan accent. Deep panels.");
                ui.colored_label(D_TX2,"Direction B (toggle): Light Mode iOS-style. White cards. Blue accent. Alternative.");
                ui.add_space(4.0);
                ui.colored_label(D_AM,"Review: info density / readability / tech feel / color differentiation / collapse fluidity");
                ui.colored_label(D_TX2,"Next: boss picks a direction from the two, v0.7.0 refines.");
            });
        });

        TopBottomPanel::bottom("bb").height_range(22.0..=28.0)
            .frame(Frame::default().fill(D_PN).inner_margin(Margin::symmetric(18,0)))
            .show(ctx,|ui|{ui.horizontal(|ui|{
                ui.colored_label(D_AC,"* wuying-01");
                ui.label("|");ui.label(RichText::new("v0.6.0 dark-mode REST-only").color(D_TX2).size(11.0));
            });});

        ctx.request_repaint_after(Duration::from_secs(5));
    }
}

fn main() -> eframe::Result {
    let shared=Arc::new(Mutex::new(Shared{ok:false,agents:vec![],tasks:vec![],fetch_ms:0}));
    let base_url=orchestrator_url();
    let s2=shared.clone();
    std::thread::spawn(move||loop{if let Ok(mut d)=s2.lock(){*d=fetch_data(&base_url);}std::thread::sleep(Duration::from_secs(5));});
    eframe::run_native("UAS Canvas",eframe::NativeOptions{
        viewport:egui::ViewportBuilder::default().with_inner_size([1440.0,900.0]).with_min_inner_size([1024.0,640.0]).with_title("UAS Canvas"),
        ..Default::default()
    },Box::new(|cc|{
        configure_fonts(&cc.egui_ctx);
        Ok(Box::new(UasCanvas::new(shared)))
    }))
}
