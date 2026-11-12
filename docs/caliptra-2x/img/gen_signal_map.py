W,H=1900,1230
o=[]
def box(x,y,w,h,fill,stroke,title=None,lines=(),ts=15):
    o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
    yy=y+22
    if title:
        o.append(f'<text x="{x+w/2}" y="{yy}" text-anchor="middle" font-weight="bold" font-size="{ts}">{title}</text>'); yy+=20
    for l in lines:
        o.append(f'<text x="{x+w/2}" y="{yy}" text-anchor="middle" font-size="12.5">{l}</text>'); yy+=17
def t(x,y,s,size=12.5,anchor="start",bold=False,fill="#111",italic=False):
    o.append(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}" fill="{fill}"{" font-weight=\"bold\"" if bold else ""}{" font-style=\"italic\"" if italic else ""}>{s}</text>')
def ln(pts,color="#333",w=1.8,end=True,start=False,dash=False):
    d=" ".join(f"{x},{y}" for x,y in pts)
    o.append(f'<polyline points="{d}" fill="none" stroke="{color}" stroke-width="{w}"{" stroke-dasharray=\"5,4\"" if dash else ""}{" marker-end=\"url(#a)\"" if end else ""}{" marker-start=\"url(#b)\"" if start else ""}/>')

CX=1180; CW=690
# ---------- Caliptra ----------
box(CX,60,CW,1110,"#fff4e6","#d9822b")
t(CX+CW/2,85,"caliptra_passive_top  (Caliptra 2.x RTL v2.1.2, passive / core-only)",16,"middle",True)
port={}
def grp(y,s): t(CX+14,y,s,13.5,bold=True,fill="#a0521d")
def p(y,name,dirn,note=""):
    # dirn: in / out / bi / tie
    port[name]=y
    sym={"in":"&#9654;","out":"&#9664;","bi":"&#8646;","tie":"&#9679;"}[dirn]
    t(CX+14,y+4,f'{sym}  <tspan font-family="monospace" font-size="13">{name}</tspan>',12.5)
    if note: t(CX+CW-12,y+4,note,12,"end",fill="#555")
grp(112,"Clock / reset")
p(132,"clk","in","single clock, shared with Nios")
p(157,"cptra_pwrgood","in","from ctrl_pio[0] via 2-FF sync")
p(182,"cptra_rst_b","in","from ctrl_pio[1] via 2-FF sync")
grp(220,"AXI4 subordinate  (data 32b, addr 19b, ID 8b, USER 32b)")
axi=[(245,"awaddr[18:0] awburst awsize awlen awid awlock","in","AW"),
     (270,"awuser[31:0]  awvalid  /  awready","bi","AW user: 1=Nios, 2=fuse ctrl"),
     (300,"wdata[31:0] wstrb[3:0] wuser[31:0] wlast","in","W"),
     (325,"wvalid  /  wready","bi",""),
     (355,"bresp[1:0]  bvalid  /  bready","bi","B (bid, buser not used)"),
     (385,"araddr[18:0] arburst arsize arlen arid arlock","in","AR"),
     (410,"aruser[31:0]  arvalid  /  arready","bi","AR user always 1 (Nios)"),
     (440,"rdata[31:0]  rresp[1:0]","out","R (rid, ruser, rlast not used)"),
     (465,"rvalid  /  rready","bi","")]
for y,n,d,nt in axi: p(y,n,d,nt)
grp(505,"Status outputs  (to status PIO, bit position shown)")
st=[(530,"ready_for_fuses","status[0]  (also to fuse ctrl)"),
    (555,"ready_for_mb_processing","status[1]"),
    (580,"ready_for_runtime","status[2]"),
    (605,"mailbox_data_avail","status[3]"),
    (630,"mailbox_flow_done","status[4]"),
    (655,"cptra_error_fatal","status[5]"),
    (680,"cptra_error_non_fatal","status[6]"),
    (705,"etrng_req","status[7]  (Nios answers with TRNG data)"),
    (730,"generic_output_wires[63:0]","[23:0] to status[31:8]  (ROM/FW log)")]
for y,n,nt in st: p(y,n,"out",nt)
grp(770,"Host control input")
p(795,"BootFSM_BrkPoint","in","from ctrl_pio[2]")
grp(835,"Tied off at the top level")
ties=[(860,"generic_input_wires[63:0] = 0","no zeroization source"),
      (885,"cptra_obf_key[255:0] = study const","NOT a real secret"),
      (910,"cptra_csr_hmac_key[511:0] = study const","NOT a real secret"),
      (935,"security_state_device_lifecycle = 2'b11","DEVICE_PRODUCTION"),
      (960,"security_state_debug_locked = 1","debug locked"),
      (985,"jtag_tck/tms/tdi/trst_n = 0","jtag_tdo, jtag_tdoEn unused"),
      (1010,"itrng_data = 0, itrng_valid = 0","external TRNG via mailbox"),
      (1035,"scan_mode = 0","")]
for y,n,nt in ties: p(y,n,"tie",nt)
o.append(f'<line x1="{CX+10}" y1="1055" x2="{CX+CW-10}" y2="1055" stroke="#d9822b" stroke-dasharray="4,3"/>')
t(CX+14,1077,"Inside the wrapper, not on the boundary:",12.5,bold=True,fill="#a0521d")
t(CX+14,1097,"mailbox SRAM 256 KiB + ECC, ROM 96 KiB (caliptra-rom.hex), VeeR ICCM/DCCM, Adams-Bridge memories;",12)
t(CX+14,1115,"AXI manager (DMA) tied never-ready (passive mode); all ss_* subsystem straps = 0;",12)
t(CX+14,1133,"cptra_obf_field_entropy / uds_seed = 0; recovery_* = 0.",12)

# ---------- Nios ----------
NX,NWd=30,360; NR=NX+NWd
box(NX,60,NWd,940,"#e8f1fb","#2b6cb0")
t(NX+NWd/2,85,"nios_caliptra2x_sys",16,"middle",True)
t(NX+NWd/2,104,"(Platform Designer)",12.5,"middle")
inner=["Nios V/m CPU","On-chip RAM (main.c / onchip_mem.hex)","JTAG UART (console)","mm_bridge: 1 MiB Avalon window","ctrl PIO (out), status PIO (in),","magic PIO (out)"]
o.append(f'<rect x="{NX+30}" y="380" width="{NWd-60}" height="140" rx="6" fill="#fff" stroke="#2b6cb0" stroke-dasharray="4,3"/>')
for i,s in enumerate(inner): t(NX+NWd/2,403+i*19,s,12.5,"middle")
def np_(y,s): t(NR-10,y+4,f'<tspan font-family="monospace" font-size="12.5">{s}</tspan>',12,"end")
np_(152,"ctrl_pio_export[31:0]")
np_(290,"caliptra_axi_* (Avalon-MM)")
np_(720,"status_pio_export[31:0]")
np_(795,"ctrl_pio_export[2]")
np_(930,"magic_pio_export[7:0]")
t(NX+12,980,"clk_clk = clk,  reset_reset_n = sys_reset_n",12,fill="#2b6cb0")

# ---------- Glue ----------
GF,GS="#eef7ee","#2f855a"
t(790,52,"nios_caliptra2x_top glue logic",15,"middle",True,fill=GS)
box(790,110,210,95,GF,GS,"Reset/power sync",["2-FF sync on ctrl[0], ctrl[1]","both ANDed with sys_reset_n","(reset_n &amp; ~ninit_done)"],14)
box(530,235,210,95,GF,GS,"Window decode",["+ readdata / waitrequest mux","addr[19] = Caliptra","addr[18:12]=0x7F = fuse"],14)
box(530,380,170,90,GF,GS,"soc_fw_store",["0x00000-0x3FFFF","FW bundle ROM","253,440 B"],14)
box(530,535,225,110,GF,GS,"soc_fuse_ctrl2x",["MMIO 0x7F000-0x7FFFF","pushes 117 fuse words","AXI writes with AxUSER = 2","sets FW size"],14)
box(790,235,200,250,GF,GS,"avmm_to_axi",["Avalon-MM to AXI4 bridge","window 0x80000-0xFFFFF","AXI addr = addr[18:0]","mbox_csr: window 0xA0000","soc_ifc: window 0xB0000","AxUSER = 1 (Nios)","response -> Avalon","response[1:0]"],14)
box(1030,235,95,250,GF,GS,None,[])
for i,s in enumerate(["AXI","write","mux","","sel =","fuse_busy","","AR / R","pass","through"]): t(1077,262+i*18,s,12,"middle")
box(1030,520,95,230,GF,GS,None,[])
for i,s in enumerate(["status","PIO","packing","","{gow[23:0],","etrng,","err_nf,","err_f, ...","rff}"]): t(1077,550+i*19,s,12,"middle")

# ---------- wires ----------
B="#2b6cb0"; G="#2f855a"; O="#c05621"
# clk
t(1100,128,"clk",12,"middle",fill="#555")
ln([(1060,132),(CX,132)],"#777")
# ctrl[1:0]
ln([(NR,152),(790,152)],B); t(420,145,"ctrl[1:0]  (reset value 0 = Caliptra held in reset)",12,fill=B)
ln([(1000,157),(CX,157)],G); ln([(1000,182),(CX,182)],G)
# avalon
ln([(NR,282),(530,282)],B); ln([(530,300),(NR,300)],B)
for i,s_ in enumerate(["address[19:0]","read, write","writedata[31:0]","byteenable[3:0]"]): t(400,226+i*15,s_,11.5,fill=B)
for i,s_ in enumerate(["readdata[31:0]","readdatavalid","waitrequest","response[1:0]"]): t(400,318+i*15,s_,11.5,fill=B)

ln([(740,282),(790,282)],G,start=True)
ln([(615,330),(615,380)],G,start=True)
ln([(725,330),(725,520),(660,520),(660,535)],G,start=True)
# bridge -> mux -> caliptra
for y,_,d,_n in axi:
    if y<=355:
        ln([(990,y),(1030,y)],G,start=(d!="in"))
        ln([(1125,y),(CX,y)],O,start=(d!="in"))
    else:
        ln([(990,y),(1030,y)],G,start=(d!="in"))
        ln([(1125,y),(CX,y)],O,start=(d!="in"))
# fuse -> mux
ln([(755,600),(1010,600),(1010,500),(1060,500),(1060,485)],G,start=True)
t(765,592,"fuse AW / W / B (AxUSER=2)",11.5,fill=G)
# status
for y,n,_ in st: ln([(CX,y),(1125,y)],O)
ln([(1030,640),(980,640),(980,720),(NR,720)],B,w=3)
t(420,712,"status[31:0]",12,fill=B)
# ready_for_fuses to fuse ctrl
ln([(1030,530),(1015,530),(1015,560),(755,560)],O,dash=True)
t(765,553,"ready_for_fuses",11.5,fill=O)
# brkpoint
ln([(NR,795),(CX,795)],B); t(420,788,"ctrl[2]  BootFSM breakpoint",12,fill=B)
# led
ln([(NR,930),(530,930)],B); t(538,935,"led[7:0]  (board LEDs)",12.5,fill=B)
# rst note
t(420,1035,"rst_release (ninit_done) + board reset_n give sys_reset_n, which drives the Nios reset and the glue 2-FF reset sync.",12,fill="#555",italic=True)

# legend
t(30,1095,"Legend:",13,bold=True)
t(30,1115,"&#9654; input to Caliptra    &#9664; output from Caliptra    &#8646; handshake (valid / ready)    &#9679; constant tie-off",12.5)
t(30,1135,"Blue = Nios side,  green = top-level glue,  orange = Caliptra boundary.   Source: caliptra2x/rtl_2x/nios_caliptra2x_top.sv, caliptra_passive_top.sv",12.5)
t(30,1155,"Nios address map: 0x00000 FW store, 0x7F000 fuse ctrl, 0x80000 Caliptra (AXI 0x00000-0x7FFFF). Nios address = 0x0010_0000 + window offset.",12.5)

svg=f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="Helvetica, Arial, sans-serif">
<defs><marker id="a" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto"><path d="M0,0 L9,4.5 L0,9 z" fill="#333"/></marker>
<marker id="b" markerWidth="9" markerHeight="9" refX="1" refY="4.5" orient="auto"><path d="M9,0 L0,4.5 L9,9 z" fill="#333"/></marker></defs>
<rect width="100%" height="100%" fill="white"/>
<text x="{W/2}" y="28" text-anchor="middle" font-size="20" font-weight="bold">Nios V  &lt;-&gt;  Caliptra 2.x signal map (nios_caliptra2x_top, Agilex 5E A5E 065)</text>
{"".join(o)}</svg>'''
open("nios_caliptra2x_signal_map.svg","w").write(svg)
