"""add brand_mappings table with seed data

Revision ID: 20260630_add_brand_mappings
Revises: 20260629_add_chat_sessions
Create Date: 2026-06-30
"""
from alembic import op

revision = "20260630_add_brand_mappings"
down_revision = "20260629_add_chat_sessions"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS brand_mappings (
            id           BIGSERIAL PRIMARY KEY,
            source_brand VARCHAR(50)  NOT NULL,
            target_brand VARCHAR(50)  NOT NULL,
            item_type    VARCHAR(50)  NOT NULL,
            source_value VARCHAR(200) NOT NULL,
            target_value VARCHAR(200) NOT NULL,
            description  TEXT,
            created_at   TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_brand_mapping_src_tgt ON brand_mappings(source_brand, target_brand)")

    # ── Seed: Siemens → Mitsubishi ──────────────────────────────────────────
    op.execute("""
        INSERT INTO brand_mappings (source_brand, target_brand, item_type, source_value, target_value, description) VALUES
        ('siemens','mitsubishi','io',
         'Ix.y (I0.0~I127.7)',
         'Xy (X0~X1FFF)',
         '数字量输入: Siemens Ix.y 点位格式(每字节8位) → Mitsubishi X十六进制格式'),
        ('siemens','mitsubishi','io',
         'Qx.y (Q0.0~Q127.7)',
         'Yy (Y0~Y1FFF)',
         '数字量输出: Siemens Qx.y → Mitsubishi Y十六进制格式'),
        ('siemens','mitsubishi','memory',
         'Mx.y (Merker位, M0.0~M8191.7)',
         'Mx (M辅助继电器, M0~M8191)',
         '位存储器: Siemens Merker位(带小数点) → Mitsubishi M辅助继电器(无小数点)'),
        ('siemens','mitsubishi','memory',
         'MWx (Merker Word 16位)',
         'Dx (数据寄存器 16位)',
         '字存储器: Siemens MWx → Mitsubishi D数据寄存器(16位)'),
        ('siemens','mitsubishi','memory',
         'MDx (Merker DWord 32位)',
         'Dx+Dx+1 (两个连续D寄存器 32位)',
         '双字: Siemens MDx 32位 → Mitsubishi两个连续D寄存器合并为DWORD'),
        ('siemens','mitsubishi','memory',
         'DB1.DBX0.0 (数据块位)',
         'Mx (M辅助继电器)',
         '数据块位 → Mitsubishi M辅助继电器; 需重新规划地址映射'),
        ('siemens','mitsubishi','memory',
         'DB1.DBW0 (数据块Word) / DB1.DBD0 (DWord)',
         'Dx / Dx+Dx+1',
         '数据块字 → Mitsubishi D寄存器; DBD32位对应两个连续D'),
        ('siemens','mitsubishi','timer',
         'T0 (S_ODT, 100ms分辨率)',
         'T0 (100ms通用定时器) / ST0 (1ms高精度)',
         '定时器: Siemens T基准100ms, IEC模式; Mitsubishi T=100ms, ST=1ms精度'),
        ('siemens','mitsubishi','counter',
         'C0 (CTU加计数 / CTD减计数 / CTUD双向)',
         'C0 (16位加计数) / DC0 (32位高速)',
         '计数器: Siemens CTU/CTD → Mitsubishi C(16位)/DC(32位)'),
        ('siemens','mitsubishi','communication',
         'PROFINET (IEC 61158, 端口102, 100Mbps+)',
         'CC-Link IE Field / CC-Link IE TSN',
         '工业以太网骨干网: PROFINET → CC-Link IE; 两者均支持1Gbps, 需网关互转'),
        ('siemens','mitsubishi','communication',
         'S7 协议 (ISO on TCP, 端口102)',
         'MC协议 (SLMP 3E/4E帧, 端口5007/5006)',
         '专有通信: Siemens S7 → Mitsubishi MC Protocol; 均支持TCP读写PLC内存'),
        ('siemens','mitsubishi','communication',
         'Modbus TCP (标准, 端口502)',
         'Modbus TCP (标准, 端口502)',
         '两者均支持 Modbus TCP, 功能码03/06/16通用, 地址映射需对照手册'),
        ('siemens','mitsubishi','instruction',
         'MOVE (数据传送Box)',
         'MOV (传送指令)',
         '数据传送: Siemens MOVE → Mitsubishi MOV'),
        ('siemens','mitsubishi','instruction',
         'ADD_I / SUB_I (16位整数加减)',
         '+P / -P (脉冲执行加减)',
         '整数运算: Siemens ADD_I → Mitsubishi加减指令; P后缀=脉冲执行'),
        ('siemens','mitsubishi','instruction',
         'CMP_EQ / CMP_LT / CMP_GT (比较)',
         'CMP / ZCP (比较 / 区间比较)',
         '比较指令: Siemens比较Box → Mitsubishi CMP或ZCP'),
        ('siemens','mitsubishi','instruction',
         'FB/FC调用 (函数块/函数)',
         'FB/SUB调用 (函数块/子程序)',
         '程序结构: Siemens FB(有状态)/FC(无状态) → Mitsubishi FB(有状态)/SUB')
    """)

    # ── Seed: Siemens → Omron ───────────────────────────────────────────────
    op.execute("""
        INSERT INTO brand_mappings (source_brand, target_brand, item_type, source_value, target_value, description) VALUES
        ('siemens','omron','io',
         'Ix.y (I0.0~I127.7)',
         'CIO 0.00~2555.15 (输入区 0.xx格式)',
         '数字量输入: Siemens Ix.y → Omron CIO通道位地址(通道.位)'),
        ('siemens','omron','io',
         'Qx.y (Q0.0~Q127.7)',
         'CIO 100.00+ (输出区从CIO100起)',
         '数字量输出: Siemens Qx.y → Omron CIO输出区(通常从100.00开始)'),
        ('siemens','omron','memory',
         'Mx.y (Merker位)',
         'Wx.yy (Work位, W区)',
         '位存储器: Siemens M位 → Omron W工作位; W区掉电不保持'),
        ('siemens','omron','memory',
         'MWx (Merker Word 16位)',
         'DMx (Data Memory, DM0~DM32767)',
         '字存储器: Siemens MWx → Omron DM数据存储区(掉电保持)'),
        ('siemens','omron','memory',
         'DB1.DBW0 (数据块Word)',
         'DMx (DM区全局访问)',
         '数据块字 → Omron DM区; DM全程序可读写, 类似Siemens DB的全局变量'),
        ('siemens','omron','timer',
         'T0 (S_ODT 接通延时, 100ms)',
         'TIM0000 (接通延时, 100ms基准)',
         '定时器: Siemens T接通延时 → Omron TIM(100ms); 高精度用TIMH(10ms)/TIML(1ms)'),
        ('siemens','omron','counter',
         'C0 (CTU 加计数)',
         'CNT0000 (减计数, 到0触发)',
         '计数器: 注意方向相反! Siemens加计数 → Omron减计数(预置值递减到0)'),
        ('siemens','omron','communication',
         'PROFINET (端口102)',
         'EtherNet/IP (端口44818 / UDP2222)',
         '工业以太网: PROFINET → EtherNet/IP; 均CIP协议族成员, 需网关互转'),
        ('siemens','omron','communication',
         'S7 协议 (端口102/TCP)',
         'FINS 协议 (UDP端口9600 / TCP端口9600)',
         '专有协议: Siemens S7 → Omron FINS; FINS支持UDP/TCP广播读写'),
        ('siemens','omron','instruction',
         'MOVE',
         'MOV(021)',
         '数据传送: Siemens MOVE → Omron MOV(021)'),
        ('siemens','omron','instruction',
         'ADD_I / SUB_I (整数加减)',
         '+B(400) / -B(410) (带借位加减)',
         '整数运算: Siemens → Omron +B/-B(带符号16位加减)')
    """)

    # ── Seed: Mitsubishi → Omron ────────────────────────────────────────────
    op.execute("""
        INSERT INTO brand_mappings (source_brand, target_brand, item_type, source_value, target_value, description) VALUES
        ('mitsubishi','omron','io',
         'X0~X1FFF (十六进制输入)',
         'CIO 0.00~2555.15 (输入区)',
         '数字量输入: Mitsubishi X(十六进制编号) → Omron CIO输入位地址'),
        ('mitsubishi','omron','io',
         'Y0~Y1FFF (十六进制输出)',
         'CIO 100.00~2655.15 (输出区)',
         '数字量输出: Mitsubishi Y → Omron CIO输出区'),
        ('mitsubishi','omron','memory',
         'M0~M8191 (M辅助继电器)',
         'W0.00~W511.15 (Work位)',
         '位存储器: Mitsubishi M → Omron W工作位(掉电不保持)'),
        ('mitsubishi','omron','memory',
         'D0~D7999 (数据寄存器 16位)',
         'DM0~DM32767 (Data Memory)',
         '字存储器: Mitsubishi D寄存器 → Omron DM数据存储区'),
        ('mitsubishi','omron','memory',
         'D0+D1 (两个连续D寄存器存32位)',
         'DM0+DM1 (两个连续DM存32位)',
         '双字: 两者均用低地址存低16位, 高地址存高16位(小端顺序)'),
        ('mitsubishi','omron','timer',
         'T0 (100ms) / ST0 (1ms高精度)',
         'TIM0000 (100ms) / TIMH (10ms) / TIML (1ms)',
         '定时器精度对应: Mitsubishi T(100ms)/ST(1ms) → Omron TIM/TIML'),
        ('mitsubishi','omron','counter',
         'C0 (16位加计数) / DC0 (32位)',
         'CNT0000 (16位减计数) / CNTL0000 (32位)',
         '计数器: 方向相反(Mitsubishi加计数 → Omron减计数); 位宽对应'),
        ('mitsubishi','omron','communication',
         'CC-Link IE Field / CC-Link IE TSN',
         'EtherNet/IP (通过Anybus网关适配)',
         '工业以太网: CC-Link IE与EtherNet/IP不互通, 需HMS Anybus等协议网关'),
        ('mitsubishi','omron','communication',
         'MC协议 (SLMP 3E/4E帧, 端口5007)',
         'FINS协议 (UDP端口9600)',
         '专有协议: 均可通过Modbus TCP中间层互通, 或使用协议转换网关'),
        ('mitsubishi','omron','instruction',
         'MOV (传送)',
         'MOV(021)',
         '数据传送: Mitsubishi MOV → Omron MOV(021)'),
        ('mitsubishi','omron','instruction',
         'CMP (单值比较) / ZCP (区间比较)',
         'CMP(020) / BCMP(068) 区间比较',
         '比较指令: Mitsubishi CMP/ZCP → Omron CMP(020)/BCMP(068)')
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS brand_mappings")
