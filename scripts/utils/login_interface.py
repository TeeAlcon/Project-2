import tkinter as tk
from tkinter import ttk
from tkinter import messagebox


def get_credentials(error_message=None):
    credentials = {"username": None, "password": None}

    def submit():
        credentials["username"] = username_var.get().strip()
        credentials["password"] = password_var.get()
        root.destroy()

    root = tk.Tk()
    root.title("Expeditors Login")
    root.geometry("350x170")
    root.resizable(False, False)

    frame = ttk.Frame(root, padding=15)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="Username. Ex: bruce.wayne@alcon.com").pack(anchor="w")
    username_var = tk.StringVar()
    ttk.Entry(frame, textvariable=username_var, width=40).pack(fill="x", pady=(0, 10))

    ttk.Label(frame, text="Password").pack(anchor="w")
    password_var = tk.StringVar()
    ttk.Entry(
        frame,
        textvariable=password_var,
        show="*",
        width=40
    ).pack(fill="x", pady=(0, 15))

    ttk.Button(frame, text="Login", command=submit).pack()

    root.lift()
    root.attributes("-topmost", True)
    root.after(100, lambda: root.attributes("-topmost", False))

    if error_message:
        messagebox.showerror("Login Failed", error_message)

    root.mainloop()

    return credentials["username"], credentials["password"]