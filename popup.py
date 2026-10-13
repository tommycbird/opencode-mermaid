#!/usr/bin/python3
import os
import sys
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, Pango

PAD = 16
BAR_H = 26
MIN_W, MIN_H = 280, 140
MAX_ZOOM = 8.0
CORNER_GRIP = 18
BRACKET_LEN = 14
BACKDROP = (0.05, 0.05, 0.10, 0.85)
USAGE = ("usage: popup.py IMAGE [--source FILE.mmd] [--title TEXT] "
         "[--timeout SECONDS] [--alpha 0.0-1.0]")

CSS = b"""
.mermaid-bar { background-color: rgba(54,58,79,0.97); }
.mermaid-bar label { color: #cad3f5; font-size: 9pt; }
.mermaid-bar button {
    background: transparent; border: none; color: #cad3f5;
    padding: 0 7px 2px 7px; font-size: 9pt;
}
.mermaid-bar button:hover { background-color: rgba(183,189,248,0.3); }
.mermaid-close {
    font-size: 14pt; padding: 0;
    min-width: 34px; min-height: 26px;
}
.mermaid-close:hover { background-color: rgba(237,135,150,0.5); }
"""


def load_pixbuf(path):
    return GdkPixbuf.Pixbuf.new_from_file(path)


class Popup(Gtk.Window):
    def __init__(self, pb, title, source, timeout, alpha):
        Gtk.Window.__init__(self, type=Gtk.WindowType.TOPLEVEL)
        r, g, b, a = BACKDROP
        self.backdrop = (r, g, b, a * alpha)
        self.pb = pb
        self.source = source
        self.zoom_level = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.mode = None
        self.press_xy = None
        self.win_xy = None
        self.pan_start = None
        self.resize_dir = None
        self.grip_size = None

        self.set_app_paintable(True)
        self.set_decorated(False)
        self.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self.set_resizable(True)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_accept_focus(True)
        self.connect("key-press-event", lambda w, e: Gtk.main_quit())

        self.cursors = {
            (-1, -1): Gdk.Cursor.new(Gdk.CursorType.TOP_LEFT_CORNER),
            (1, -1): Gdk.Cursor.new(Gdk.CursorType.TOP_RIGHT_CORNER),
            (-1, 1): Gdk.Cursor.new(Gdk.CursorType.BOTTOM_LEFT_CORNER),
            (1, 1): Gdk.Cursor.new(Gdk.CursorType.BOTTOM_RIGHT_CORNER),
            None: None,
            "hand": Gdk.Cursor.new(Gdk.CursorType.HAND2),
        }

        bar = Gtk.EventBox()
        bar.get_style_context().add_class("mermaid-bar")
        bar.set_size_request(-1, BAR_H)
        bar.connect("button-press-event", self.on_bar_press)
        bar.connect("motion-notify-event", self.on_bar_motion)
        bar.connect_after("draw", self.on_bar_draw)
        bar.connect("scroll-event", self.on_scroll)
        bar.add_events(Gdk.EventMask.BUTTON_PRESS_MASK
                       | Gdk.EventMask.BUTTON1_MOTION_MASK
                       | Gdk.EventMask.POINTER_MOTION_MASK
                       | Gdk.EventMask.SCROLL_MASK)
        hbox = Gtk.Box(spacing=2)
        hbox.set_margin_end(CORNER_GRIP)
        lbl = Gtk.Label(title)
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        lbl.set_halign(Gtk.Align.START)
        hbox.pack_start(lbl, True, True, CORNER_GRIP)
        if source is not None:
            copy_btn = Gtk.Button()
            copy_btn.set_relief(Gtk.ReliefStyle.NONE)
            copy_btn.set_label("copy")
            copy_btn.connect("clicked", self.on_copy)
            hbox.pack_start(copy_btn, False, False, 0)
        close_btn = Gtk.Button()
        close_btn.set_relief(Gtk.ReliefStyle.NONE)
        close_btn.get_style_context().add_class("mermaid-close")
        close_btn.set_label("\u00d7")
        close_btn.connect("clicked", lambda b: Gtk.main_quit())
        hbox.pack_start(close_btn, False, False, 0)
        bar.add(hbox)

        content = Gtk.DrawingArea()
        content.set_hexpand(True)
        content.set_vexpand(True)
        content.set_size_request(4, 4)
        content.connect("draw", self.on_draw)
        content.connect("button-press-event", self.on_press)
        content.connect("motion-notify-event", self.on_motion)
        content.connect("scroll-event", self.on_scroll)
        content.add_events(Gdk.EventMask.BUTTON_PRESS_MASK
                           | Gdk.EventMask.BUTTON1_MOTION_MASK
                           | Gdk.EventMask.POINTER_MOTION_MASK
                           | Gdk.EventMask.SCROLL_MASK)
        self.content = content

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        vbox.pack_start(bar, False, False, 0)
        vbox.pack_start(content, True, True, 0)
        self.add(vbox)

        visual = self.get_screen().get_rgba_visual()
        if visual is not None and self.get_screen().is_composited():
            self.set_visual(visual)
        if timeout > 0:
            GLib.timeout_add_seconds(timeout, Gtk.main_quit)

        self.mon = self.get_screen().get_monitor_workarea(0)
        self.bounds = self.screen_bounds()
        w0 = min(pb.get_width() + 2 * PAD, int(self.mon.width * 0.85))
        h0 = min(pb.get_height() + 2 * PAD + BAR_H, int(self.mon.height * 0.85))
        self.set_default_size(w0, h0)
        self.position_center()
        self.show_all()
        self.present()
        content.get_window().set_cursor(self.cursors["hand"])

    def screen_bounds(self):
        s = self.get_screen()
        n = s.get_n_monitors()
        geoms = [s.get_monitor_geometry(i) for i in range(n)]
        return (min(g.x for g in geoms),
                min(g.y for g in geoms),
                max(g.x + g.width for g in geoms),
                max(g.y + g.height for g in geoms))

    def position_center(self):
        w, h = self.get_default_size()
        x = self.mon.x + (self.mon.width - w) // 2
        y = self.mon.y + max(0, (self.mon.height - h) // 3)
        self.move(x, y)

    def corner_at(self, x, y, w, h):
        gx = -1 if x < CORNER_GRIP else (1 if x > w - CORNER_GRIP else 0)
        gy = -1 if y < CORNER_GRIP else (1 if y > h - CORNER_GRIP else 0)
        if gx != 0 and gy != 0:
            return (gx, gy)
        return None

    def begin_interaction(self, w, e, default):
        if e.button != 1:
            return True
        alloc = w.get_allocation()
        corner = self.corner_at(e.x, e.y, alloc.width, alloc.height)
        if corner is not None:
            self.mode = "resize"
            self.resize_dir = corner
            self.press_xy = (e.x_root, e.y_root)
            self.win_xy = self.get_position()
            self.grip_size = self.get_size()
        elif default == "move":
            self.mode = "move"
            self.press_xy = (e.x_root, e.y_root)
            self.win_xy = self.get_position()
        else:
            self.mode = "pan"
            self.press_xy = (e.x, e.y)
            self.pan_start = (self.pan_x, self.pan_y)
        return True

    def on_bar_press(self, w, e):
        return self.begin_interaction(w, e, "move")

    def on_press(self, w, e):
        return self.begin_interaction(w, e, "pan")

    def dragging(self, e):
        return self.mode is not None and (e.state & Gdk.ModifierType.BUTTON1_MASK)

    def hover_cursor(self, w, e, default):
        alloc = w.get_allocation()
        corner = self.corner_at(e.x, e.y, alloc.width, alloc.height)
        w.get_window().set_cursor(self.cursors.get(corner, default))

    def on_bar_motion(self, w, e):
        if not self.dragging(e):
            self.hover_cursor(w, e, self.cursors[None])
            return False
        if self.mode == "resize":
            self.do_resize(e)
        elif self.mode == "move":
            self.move_window(e)
        return True

    def on_motion(self, w, e):
        if not self.dragging(e):
            self.hover_cursor(w, e, self.cursors["hand"])
            return False
        if self.mode == "resize":
            self.do_resize(e)
        elif self.mode == "pan":
            self.pan_x = self.pan_start[0] + (e.x - self.press_xy[0])
            self.pan_y = self.pan_start[1] + (e.y - self.press_xy[1])
            self.clamp_pan()
            self.content.queue_draw()
        return True

    def move_window(self, e):
        dx = e.x_root - self.press_xy[0]
        dy = e.y_root - self.press_xy[1]
        x1, y1, x2, y2 = self.bounds
        w, h = self.get_size()
        x = min(max(self.win_xy[0] + int(dx), x1 - w + 100), x2 - 100)
        y = min(max(self.win_xy[1] + int(dy), y1 - h + BAR_H + 10),
                 y2 - BAR_H - 4)
        self.move(x, y)

    def do_resize(self, e):
        hx, hy = self.resize_dir
        dx = e.x_root - self.press_xy[0]
        dy = e.y_root - self.press_xy[1]
        nw = int(min(max(self.grip_size[0] + hx * dx, MIN_W), self.mon.width))
        nh = int(min(max(self.grip_size[1] + hy * dy, MIN_H), self.mon.height))
        nx = self.win_xy[0] + (self.grip_size[0] - nw if hx < 0 else 0)
        ny = self.win_xy[1] + (self.grip_size[1] - nh if hy < 0 else 0)
        self.move(nx, ny)
        self.resize(nw, nh)

    def content_size(self):
        return (self.content.get_allocated_width(),
                self.content.get_allocated_height())

    def fit_scale(self, w, h):
        return min((w - 2 * PAD) / float(self.pb.get_width()),
                   (h - 2 * PAD) / float(self.pb.get_height()))

    def drawn_size(self):
        w, h = self.content_size()
        s = self.fit_scale(w, h) * self.zoom_level
        return (self.pb.get_width() * s, self.pb.get_height() * s, w, h)

    def clamp_pan(self):
        dw, dh, w, h = self.drawn_size()
        ox = max(0.0, (dw - w) / 2.0)
        oy = max(0.0, (dh - h) / 2.0)
        self.pan_x = min(max(self.pan_x, -ox), ox)
        self.pan_y = min(max(self.pan_y, -oy), oy)

    def on_scroll(self, w, e):
        if e.direction == Gdk.ScrollDirection.UP:
            factor = 1.15
        elif e.direction == Gdk.ScrollDirection.DOWN:
            factor = 0.87
        elif e.direction == Gdk.ScrollDirection.SMOOTH:
            factor = 1.15 if (e.delta_y < 0 or e.delta_x > 0) else 0.87
        else:
            return False
        ca = self.content.get_allocation()
        wa = w.get_allocation()
        cx = e.x + wa.x - ca.x
        cy = e.y + wa.y - ca.y
        self.zoom_image(factor, cx, cy)
        return True

    def zoom_image(self, factor, cx, cy):
        w, h = self.content_size()
        if w < 2 or h < 2:
            return
        old = self.zoom_level
        new = min(max(old * factor, 1.0), MAX_ZOOM)
        if new == old:
            return
        fit = self.fit_scale(w, h)
        dw_old = self.pb.get_width() * fit * old
        dh_old = self.pb.get_height() * fit * old
        x_old = (w - dw_old) / 2.0 + self.pan_x
        y_old = (h - dh_old) / 2.0 + self.pan_y
        s_old = fit * old
        if s_old > 0 and dw_old > 0 and dh_old > 0:
            u = (cx - x_old) / s_old
            v = (cy - y_old) / s_old
        else:
            u = self.pb.get_width() / 2.0
            v = self.pb.get_height() / 2.0
        s_new = fit * new
        dw_new = self.pb.get_width() * s_new
        dh_new = self.pb.get_height() * s_new
        self.pan_x = cx - (w - dw_new) / 2.0 - u * s_new
        self.pan_y = cy - (h - dh_new) / 2.0 - v * s_new
        self.zoom_level = new
        self.clamp_pan()
        self.content.queue_draw()

    def on_copy(self, btn):
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(self.source, -1)
        btn.set_label("copied \u2713")
        GLib.timeout_add(1200, lambda: (btn.set_label("copy"), False)[1])

    def stroke_brackets(self, cr, w, h, top):
        cr.set_source_rgba(1, 1, 1, 0.65)
        cr.set_line_width(2)
        L = BRACKET_LEN
        if top:
            cr.move_to(1, L)
            cr.line_to(1, 1)
            cr.line_to(L, 1)
            cr.move_to(w - L, 1)
            cr.line_to(w - 1, 1)
            cr.line_to(w - 1, L)
        else:
            cr.move_to(1, h - L)
            cr.line_to(1, h - 1)
            cr.line_to(L, h - 1)
            cr.move_to(w - L, h - 1)
            cr.line_to(w - 1, h - 1)
            cr.line_to(w - 1, h - L)
        cr.stroke()

    def on_bar_draw(self, w, cr):
        alloc = w.get_allocation()
        self.stroke_brackets(cr, alloc.width, alloc.height, True)
        return False

    def on_draw(self, da, cr):
        w = da.get_allocated_width()
        h = da.get_allocated_height()
        if w < 2 or h < 2:
            return True
        cr.set_source_rgba(*self.backdrop)
        cr.paint()
        s = self.fit_scale(w, h) * self.zoom_level
        if s <= 0:
            return True
        dw = self.pb.get_width() * s
        dh = self.pb.get_height() * s
        self.clamp_pan()
        cr.save()
        cr.translate((w - dw) / 2.0 + self.pan_x, (h - dh) / 2.0 + self.pan_y)
        cr.scale(s, s)
        Gdk.cairo_set_source_pixbuf(cr, self.pb, 0, 0)
        cr.paint()
        cr.restore()
        self.stroke_brackets(cr, w, h, False)
        return True


def main():
    args = sys.argv[1:]
    if not args:
        print(USAGE)
        sys.exit(1)
    path = args[0]
    source_path = None
    title = None
    timeout = 0
    alpha = 1.0
    it = iter(args[1:])
    for a in it:
        if a == "--source":
            source_path = next(it)
        elif a == "--title":
            title = next(it)
        elif a == "--timeout":
            timeout = int(next(it))
        elif a == "--alpha":
            alpha = float(next(it))
    source = None
    if source_path is not None:
        with open(source_path) as f:
            source = f.read()
    if title is None:
        title = os.path.basename(source_path) if source_path else os.path.basename(path)

    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    Popup(load_pixbuf(path), title, source, timeout, alpha)
    Gtk.main()


if __name__ == "__main__":
    main()
