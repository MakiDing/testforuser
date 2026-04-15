#成功运行版
#尝试让端口可以同时输入三个板子数据
#三个板子都能成功连接上，哈哈
import asyncio
import math
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from bleak import BleakScanner, BleakClient

SERVICE_UUID = "88430f7e-40d3-5ac0-b4d4-6c87ab5cc938"
CHAR_UUID = "585a00f9-e73a-57db-b8b7-225bbcc35b96"

TARGET_NAMES = [
    "WROOM32E-BLE-FZ-1",
    "WROOM32E-BLE-FZ-2",
    "WROOM32E-BLE-FZ-3",
]

SEND_DT = 0.2
SINE_FREQ = 0.4
CONNECT_GAP = 4.0
START_STAGGER = {
    "WROOM32E-BLE-FZ-1": 0.0,
    "WROOM32E-BLE-FZ-2": 1.0,
    "WROOM32E-BLE-FZ-3": 2.0
}
RECONNECT_DELAY = 5.0

state_lock = threading.Lock()
shared_state = {
    "running": True,
    "devices": {
        name: {
            "connected": False,
            "status": "未连接",
            "fz": 30,
            "mode": "fixed",
        }
        for name in TARGET_NAMES
    }
}


def set_device_status(name: str, text: str):
    with state_lock:
        shared_state["devices"][name]["status"] = text
    try:
        ui_refs[name]["status_var"].set(text)
    except Exception:
        pass


def set_device_connected(name: str, flag: bool):
    with state_lock:
        shared_state["devices"][name]["connected"] = flag


def get_device_state(name: str):
    with state_lock:
        d = shared_state["devices"][name].copy()
        running = shared_state["running"]
    return running, d


async def find_one_device(target_name: str, timeout: float = 12.0):
    scan_status_var.set(f"查找: {target_name}")
    try:
        dev = await BleakScanner.find_device_by_name(target_name, timeout=timeout)
        if dev:
            print(f"找到 {target_name} → {dev.address}")
            return dev
    except Exception as e:
        print(f"查找失败 {target_name}: {e}")

    def _filter(device, adv):
        name = device.name or adv.local_name or ""
        uuids = adv.service_uuids or []
        return target_name in name or SERVICE_UUID.lower() in [u.lower() for u in uuids]

    try:
        dev = await BleakScanner.find_device_by_filter(_filter, timeout=timeout)
        if dev:
            print(f"找到 {target_name} → {dev.address}")
            return dev
    except Exception as e:
        print(f"查找失败 {target_name}: {e}")
    return None


async def connect_and_stream(device_name: str, ble_device):
    t = 0.0
    last_sent = None
    set_device_status(device_name, "连接中...")

    while shared_state["running"]:
        try:
            async with BleakClient(ble_device, timeout=20.0) as client:
                if not client.is_connected:
                    set_device_status(device_name, "连接失败，将重试...")
                    await asyncio.sleep(RECONNECT_DELAY)
                    continue

                set_device_connected(device_name, True)
                set_device_status(device_name, "✅ 已连接")
                print(f"连接成功: {device_name}")

                await asyncio.sleep(START_STAGGER.get(device_name, 0.0))

                while True:
                    running, d = get_device_state(device_name)
                    if not running:
                        break
                    if not client.is_connected:
                        break

                    base_fz = int(d["fz"])
                    mode = d["mode"]

                    if mode == "fixed":
                        send_fz = base_fz
                    else:
                        send_fz = int(base_fz + 20 * math.sin(2 * math.pi * SINE_FREQ * t))
                        send_fz = max(0, min(100, send_fz))

                    if mode == "fixed" and last_sent == send_fz:
                        await asyncio.sleep(SEND_DT)
                        continue

                    payload = bytes([send_fz])
                    await client.write_gatt_char(CHAR_UUID, payload, response=False)
                    last_sent = send_fz

                    set_device_status(device_name, f"✅ Fz={send_fz/10:.1f}N")
                    t += SEND_DT
                    await asyncio.sleep(SEND_DT)

        except Exception as e:
            set_device_status(device_name, f"❌ 异常，{RECONNECT_DELAY}秒后重试")
            print(f"错误 {device_name}: {e}")
        finally:
            set_device_connected(device_name, False)
            if shared_state["running"]:
                await asyncio.sleep(RECONNECT_DELAY)
            else:
                set_device_status(device_name, "🔴 已断开")
                break


async def ble_main():
    found = {}
    for name in TARGET_NAMES:
        if not shared_state["running"]:
            break
        dev = await find_one_device(name, timeout=12.0)
        if dev:
            found[name] = dev
        else:
            set_device_status(name, "未找到设备")

    scan_status_var.set(f"找到 {len(found)}/3")
    if not found:
        return

    tasks = []
    for name in TARGET_NAMES:
        if name in found:
            await asyncio.sleep(CONNECT_GAP)
            task = asyncio.create_task(connect_and_stream(name, found[name]))
            tasks.append(task)

    if tasks:
        await asyncio.gather(*tasks)


def ble_thread_func():
    asyncio.run(ble_main())


def update_slider_label(name: str, value: int):
    ui_refs[name]["fz_var"].set(f"Fz: {value} → {value/10:.1f}N")


def on_slider_change(name: str, value):
    v = int(float(value))
    with state_lock:
        shared_state["devices"][name]["fz"] = v
    update_slider_label(name, v)


def add_fz(name: str, delta: int):
    with state_lock:
        new_v = max(0, min(100, shared_state["devices"][name]["fz"] + delta))
        shared_state["devices"][name]["fz"] = new_v
    ui_refs[name]["slider_var"].set(new_v)
    update_slider_label(name, new_v)


def set_mode(name: str, mode: str):
    with state_lock:
        shared_state["devices"][name]["mode"] = mode
    ui_refs[name]["mode_var"].set(mode)


def set_all_fz(value: int):
    for name in TARGET_NAMES:
        with state_lock:
            shared_state["devices"][name]["fz"] = value
        ui_refs[name]["slider_var"].set(value)
        update_slider_label(name, value)


def set_all_mode(mode: str):
    for name in TARGET_NAMES:
        with state_lock:
            shared_state["devices"][name]["mode"] = mode
        ui_refs[name]["mode_var"].set(mode)

# ====================== 支持多板同时控制的串口指令 ======================
def send_serial_command():
    cmd = entry_cmd.get().strip()
    if not cmd:
        return
    try:
        parts = cmd.split()
        if len(parts) % 2 != 0:
            raise ValueError("格式错误：必须是 板号 力度 成对出现")

        success_cmds = []
        # 遍历所有成对指令，支持 1、2、3 块板同时控制
        for i in range(0, len(parts), 2):
            idx_str = parts[i]
            val_str = parts[i+1]
            idx = int(idx_str)
            val = int(val_str)
            val = max(0, min(100, val))

            if idx < 1 or idx > 3:
                raise ValueError(f"板号 {idx} 只能是 1/2/3")

            name = TARGET_NAMES[idx-1]
            with state_lock:
                shared_state["devices"][name]["fz"] = val
                shared_state["devices"][name]["mode"] = "fixed"
            ui_refs[name]["slider_var"].set(val)
            ui_refs[name]["mode_var"].set("fixed")
            update_slider_label(name, val)
            success_cmds.append(f"板{idx}={val}")

        entry_cmd.delete(0, tk.END)
        scan_status_var.set(f"指令已发送 → {', '.join(success_cmds)}")
    except Exception as e:
        messagebox.showerror("格式错误", f"输入格式错误：\n{e}\n正确示例：1 20 2 30 3 40（同时控制板1/2/3）")


def on_close():
    with state_lock:
        shared_state["running"] = False
    root.destroy()


# ====================== 带滚动条的UI ======================
root = tk.Tk()
root.title("三指机械手 BLE 稳定版（可滚动+多板指令）")
root.geometry("850x700")

main_frame = ttk.Frame(root)
main_frame.pack(fill="both", expand=True)

canvas = tk.Canvas(main_frame)
scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
scrollable_frame = ttk.Frame(canvas)

scrollable_frame.bind(
    "<Configure>",
    lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
)

canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
canvas.configure(yscrollcommand=scrollbar.set)

canvas.pack(side="left", fill="both", expand=True)
scrollbar.pack(side="right", fill="y")

title = ttk.Label(scrollable_frame, text="三指机械手 BLE 控制器（三块独立）", font=("Arial", 16))
title.pack(pady=10)

scan_status_var = tk.StringVar(value="未开始扫描")
scan_status = ttk.Label(scrollable_frame, textvariable=scan_status_var, font=("Arial", 12))
scan_status.pack(pady=8)

top_btn_frame = ttk.Frame(scrollable_frame)
top_btn_frame.pack(pady=8)
ttk.Button(top_btn_frame, text="全部 30", command=lambda: set_all_fz(30)).grid(row=0, column=0, padx=8)
ttk.Button(top_btn_frame, text="全部 fixed", command=lambda: set_all_mode("fixed")).grid(row=0, column=1, padx=8)
ttk.Button(top_btn_frame, text="全部 sine", command=lambda: set_all_mode("sine")).grid(row=0, column=2, padx=8)

ui_refs = {}
for idx, name in enumerate(TARGET_NAMES, 1):
    frame = ttk.LabelFrame(scrollable_frame, text=f"板{idx}: {name}")
    frame.pack(fill="x", padx=20, pady=8)

    slider_var = tk.IntVar(value=30)
    fz_var = tk.StringVar(value="Fz: 30 → 3.0N")
    mode_var = tk.StringVar(value="fixed")
    status_var = tk.StringVar(value="未连接")

    slider = ttk.Scale(frame, from_=0, to=100, variable=slider_var, command=lambda v, n=name: on_slider_change(n, v))
    slider.pack(fill="x", padx=16, pady=6)

    ttk.Label(frame, textvariable=fz_var).pack(pady=2)

    btns = ttk.Frame(frame)
    btns.pack(pady=4)
    ttk.Button(btns, text="-5", command=lambda n=name: add_fz(n, -5)).grid(row=0, column=0, padx=6)
    ttk.Button(btns, text="+5", command=lambda n=name: add_fz(n, +5)).grid(row=0, column=1, padx=6)
    ttk.Button(btns, text="固定", command=lambda n=name: set_mode(n, "fixed")).grid(row=0, column=2, padx=6)
    ttk.Button(btns, text="正弦", command=lambda n=name: set_mode(n, "sine")).grid(row=0, column=3, padx=6)

    ttk.Label(frame, textvariable=mode_var).pack(pady=2)
    ttk.Label(frame, textvariable=status_var, font=("Arial", 10, "bold")).pack(pady=4)

    ui_refs[name] = {
        "slider_var": slider_var,
        "fz_var": fz_var,
        "mode_var": mode_var,
        "status_var": status_var
    }

serial_frame = ttk.LabelFrame(scrollable_frame, text="串口指令（手动测试，支持多板）")
serial_frame.pack(fill="x", padx=20, pady=15)
entry_cmd = ttk.Entry(serial_frame, font=("Arial", 14))
entry_cmd.pack(fill="x", padx=10, pady=8)
entry_cmd.bind("<Return>", lambda e: send_serial_command())
ttk.Label(serial_frame, text="格式：1 20 2 30 → 同时控制板1(20)和板2(30)").pack(pady=2)
ttk.Button(serial_frame, text="发送", command=send_serial_command).pack(pady=4)

root.protocol("WM_DELETE_WINDOW", on_close)
threading.Thread(target=ble_thread_func, daemon=True).start()
root.mainloop()
