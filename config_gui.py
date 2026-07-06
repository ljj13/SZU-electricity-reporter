import json
from pathlib import Path


def configure(config: dict, default_config: dict, validate_func, config_path: Path,
              errors: list = None) -> dict | None:
    """Show a small Tkinter config form and save config.json."""
    import tkinter as tk
    from tkinter import messagebox

    merged = default_config.copy()
    merged.update(config or {})
    result = {'config': None}

    root = tk.Tk()
    root.title('SZU 宿舍电量提醒配置')
    root.resizable(False, False)

    vars_map = {
        'room_name': tk.StringVar(value=str(merged.get('room_name', ''))),
        'room_id': tk.StringVar(value=str(merged.get('room_id', ''))),
        'client': tk.StringVar(value=str(merged.get('client', ''))),
        'server_chan_key': tk.StringVar(value=str(merged.get('server_chan_key', ''))),
        'interval_day': tk.StringVar(value=str(merged.get('interval_day', 14))),
        'remind_time': tk.StringVar(value=str(merged.get('remind_time', 9))),
        'low_power_threshold': tk.StringVar(value=str(merged.get('low_power_threshold', 20))),
        'remind_daily': tk.BooleanVar(value=bool(merged.get('remind_daily', False))),
        'dry_run': tk.BooleanVar(value=bool(merged.get('dry_run', False))),
    }

    frame = tk.Frame(root, padx=18, pady=16)
    frame.grid(row=0, column=0)

    if errors:
        tk.Label(
            frame,
            text='请先补全配置：' + '；'.join(errors),
            fg='#b00020',
            wraplength=440,
            justify='left',
        ).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 12))

    fields = [
        ('room_name', '房间号'),
        ('room_id', '楼栋 ID'),
        ('client', '内网 IP / client'),
        ('server_chan_key', 'Server酱 SendKey'),
        ('interval_day', '拉取最近天数'),
        ('remind_time', '每日提醒小时'),
        ('low_power_threshold', '低电量阈值'),
    ]

    offset = 1
    for index, (key, label) in enumerate(fields):
        tk.Label(frame, text=label).grid(
            row=index + offset, column=0, sticky='e', padx=(0, 8), pady=5)
        show = '*' if key == 'server_chan_key' else ''
        tk.Entry(frame, width=38, textvariable=vars_map[key], show=show).grid(
            row=index + offset, column=1, sticky='w', pady=5)

    row = len(fields) + offset
    tk.Checkbutton(frame, text='每天定时提醒', variable=vars_map['remind_daily']).grid(
        row=row, column=1, sticky='w', pady=(8, 0))
    tk.Checkbutton(frame, text='dry_run（不发送微信）', variable=vars_map['dry_run']).grid(
        row=row + 1, column=1, sticky='w')

    def on_save():
        try:
            next_config = default_config.copy()
            next_config.update({
                'room_name': vars_map['room_name'].get().strip(),
                'room_id': vars_map['room_id'].get().strip(),
                'client': vars_map['client'].get().strip(),
                'server_chan_key': vars_map['server_chan_key'].get().strip(),
                'interval_day': int(vars_map['interval_day'].get().strip()),
                'remind_time': int(vars_map['remind_time'].get().strip()),
                'low_power_threshold': float(vars_map['low_power_threshold'].get().strip()),
                'remind_daily': vars_map['remind_daily'].get(),
                'dry_run': vars_map['dry_run'].get(),
            })
        except ValueError:
            messagebox.showerror('配置错误', '拉取天数、提醒小时、低电量阈值必须是数字。')
            return

        validation_errors = validate_func(next_config)
        if validation_errors:
            messagebox.showerror('配置错误', '\n'.join(validation_errors))
            return

        config_path.write_text(
            json.dumps(next_config, ensure_ascii=False, indent=2) + '\n',
            encoding='utf-8',
        )
        result['config'] = next_config
        messagebox.showinfo('已保存', f'配置已保存到：\n{config_path}')
        root.destroy()

    buttons = tk.Frame(frame)
    buttons.grid(row=row + 2, column=0, columnspan=2, sticky='e', pady=(14, 0))
    tk.Button(buttons, text='取消', command=root.destroy, width=10).grid(
        row=0, column=0, padx=(0, 8))
    tk.Button(buttons, text='保存并运行', command=on_save, width=14).grid(row=0, column=1)

    root.mainloop()
    return result['config']
