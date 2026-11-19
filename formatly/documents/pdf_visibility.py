"""Carry PDF text painting state into the character evidence used for checks."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from pdfminer.layout import LTChar, LTPage
from pdfminer.pdfcolor import PDFColorSpace
from pdfminer.pdfdevice import PDFDevice
from pdfminer.pdffont import PDFFont, PDFUnicodeNotDefined
from pdfminer.pdfinterp import PDFGraphicState, PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.pdftypes import dict_value, resolve1
from pdfminer.psparser import literal_name
from pdfminer.utils import Matrix, apply_matrix_pt
from pdfplumber.page import Page, PDFPageAggregatorWithMarkedContent

if TYPE_CHECKING:
    from pdfplumber.pdf import PDF


class _PaintState(PDFGraphicState):
    fill_alpha = 1.0
    stroke_alpha = 1.0
    uncertain_paint = False
    soft_mask = False
    clip_bounds: tuple[float, float, float, float] | None = None

    def copy(self):
        state = _PaintState()
        state.__dict__.update(self.__dict__)
        return state


class _PaintInterpreter(PDFPageInterpreter):
    graphicstate: _PaintState

    def __init__(self, rsrcmgr: PDFResourceManager, device: PDFDevice) -> None:
        super().__init__(rsrcmgr, device)
        self._text_clip_pending = False

    def init_state(self, ctm: Matrix) -> None:
        super().init_state(ctm)
        self.graphicstate = _PaintState()
        self._text_clip_pending = False

    def do_BT(self):
        super().do_BT()
        self._text_clip_pending = False

    def do_TJ(self, seq):
        super().do_TJ(seq)
        if self.textstate.render in (4, 5, 6, 7) and seq:
            self._text_clip_pending = True

    def do_ET(self):
        # PDF applies text clipping at the end of the text object. The
        # interpreter's real state must retain it; the device sees a copy.
        if self._text_clip_pending:
            self.graphicstate.uncertain_paint = True
        self._text_clip_pending = False

    def do_gs(self, name):
        states = dict_value(self.resources.get("ExtGState", {}))
        parameters = dict_value(states.get(literal_name(name), {}))
        for key, attribute in (("ca", "fill_alpha"), ("CA", "stroke_alpha")):
            if key in parameters:
                value = resolve1(parameters[key])
                if isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 1:
                    setattr(self.graphicstate, attribute, float(value))
                else:
                    self.graphicstate.uncertain_paint = True
        if "SMask" in parameters:
            mask = resolve1(parameters["SMask"])
            # A soft mask can hide otherwise painted characters. Do not infer
            # its per-pixel effect from the text layer.
            self.graphicstate.soft_mask = getattr(mask, "name", None) != "None"

    def _set_clip(self):
        path = self.curpath
        if len(path) == 5 and [item[0] for item in path] == ["m", "l", "l", "l", "h"]:
            points: list[tuple[float, float]] = []
            for command in path[:4]:
                if len(command) != 3:
                    self.graphicstate.uncertain_paint = True
                    return
                _, point_x, point_y = command
                if not isinstance(point_x, (int, float)) or not isinstance(point_y, (int, float)):
                    self.graphicstate.uncertain_paint = True
                    return
                points.append(apply_matrix_pt(self.ctm, (float(point_x), float(point_y))))
            xs, ys = sorted({point[0] for point in points}), sorted({point[1] for point in points})
            if (len(set(points)) == 4 and len(xs) == 2 and len(ys) == 2 and all(math.isfinite(value) for value in [*xs, *ys])
                    and all(a[0] == b[0] or a[1] == b[1] for a, b in zip(points, points[1:] + points[:1]))):
                bounds = (xs[0], ys[0], xs[1], ys[1])
                current = self.graphicstate.clip_bounds
                self.graphicstate.clip_bounds = ((max(current[0], bounds[0]), max(current[1], bounds[1]),
                                                 min(current[2], bounds[2]), min(current[3], bounds[3])) if current else bounds)
                return
        self.graphicstate.uncertain_paint = True

    def do_W(self):
        self._set_clip()

    def do_W_a(self):
        self._set_clip()


class _PaintAggregator(PDFPageAggregatorWithMarkedContent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._visibility = "unverified"
        self._figure_depth = 0
        self._clip_bounds: tuple[float, float, float, float] | None = None
        self._optional_stack: list[bool] = []

    def begin_tag(self, tag, props=None):
        super().begin_tag(tag, props)
        self._optional_stack.append(bool(self._optional_stack and self._optional_stack[-1]) or getattr(tag, "name", None) == "OC")

    def end_tag(self):
        super().end_tag()
        if self._optional_stack:
            self._optional_stack.pop()

    def begin_figure(self, name, bbox, matrix):
        self._figure_depth += 1
        super().begin_figure(name, bbox, matrix)

    def end_figure(self, name):
        super().end_figure(name)
        self._figure_depth -= 1

    def render_string(self, textstate, seq, ncs, graphicstate):
        mode = textstate.render
        fill = getattr(graphicstate, "fill_alpha", 1.0)
        stroke = getattr(graphicstate, "stroke_alpha", 1.0)
        self._clip_bounds = getattr(graphicstate, "clip_bounds", None)
        if mode in (3, 7) or (mode in (0, 4) and not fill) or (mode in (1, 5) and not stroke) or (mode in (2, 6) and not (fill or stroke)):
            self._visibility = "hidden"
        elif (mode not in (0, 1, 2) or self._figure_depth or (self._optional_stack and self._optional_stack[-1])
              or getattr(graphicstate, "uncertain_paint", True) or getattr(graphicstate, "soft_mask", True)):
            self._visibility = "unverified"
        else:
            self._visibility = "painted"
        super().render_string(textstate, seq, ncs, graphicstate)

    def render_char(self, matrix: Matrix, font: PDFFont, fontsize: float, scaling: float,
                    rise: float, cid: int, ncs: PDFColorSpace, graphicstate: PDFGraphicState) -> float:
        # The public character-rendering hook owns the new item, so evidence
        # does not need access to a layout container's private object list.
        try:
            text = font.to_unichr(cid)
            assert isinstance(text, str), str(type(text))
        except PDFUnicodeNotDefined:
            text = self.handle_undefined_char(font, cid)
        item = LTChar(matrix, font, fontsize, scaling, rise, text, font.char_width(cid),
                      font.char_disp(cid), ncs, graphicstate)
        visibility = self._visibility
        if self._clip_bounds:
            left, bottom, right, top = self._clip_bounds
            x0, y0, x1, y1 = item.bbox
            if right <= left or top <= bottom or x1 <= left or x0 >= right or y1 <= bottom or y0 >= top:
                visibility = "hidden"
            elif visibility == "painted" and (x0 < left or y0 < bottom or x1 > right or y1 > top):
                visibility = "unverified"
        setattr(item, "paint_visibility", visibility)
        setattr(item, "mcid", self.cur_mcid)
        setattr(item, "tag", self.cur_tag)
        self.cur_item.add(item)
        return item.adv


class EvidencePage(Page):
    """A pdfplumber page whose extraction retains per-character paint state.

    Complex clipping, soft masks and Form XObject inheritance need visual
    verification; their text stays auxiliary instead of proving visible fonts.
    """

    def __init__(self, pdf: PDF, page_obj: PDFPage, page_number: int, initial_doctop: float = 0) -> None:
        super().__init__(pdf, page_obj, page_number, initial_doctop)
        # Keep the inherited lazy-cache contract: flush_cache removes this
        # attribute, and the next layout access must build it again.
        self._layout: LTPage | None = None

    @property
    def layout(self) -> LTPage:
        cached_layout = getattr(self, "_layout", None)
        if cached_layout is None:
            device = _PaintAggregator(self.pdf.rsrcmgr, pageno=self.page_number, laparams=self.pdf.laparams)
            try:
                _PaintInterpreter(self.pdf.rsrcmgr, device).process_page(self.page_obj)
                cached_layout = device.get_result()
                self._layout = cached_layout
            finally:
                device.close()
        return cached_layout

    def process_object(self, obj):
        attributes = super().process_object(obj)
        if isinstance(obj, LTChar):
            visibility = getattr(obj, "paint_visibility", "unverified")
            left, top = max(self.mediabox[0], self.cropbox[0]), max(self.mediabox[1], self.cropbox[1])
            right, bottom = min(self.mediabox[2], self.cropbox[2]), min(self.mediabox[3], self.cropbox[3])
            x0, y0, x1, y1 = (attributes[key] for key in ("x0", "top", "x1", "bottom"))
            if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
                visibility = "unverified"
            elif x1 <= left or x0 >= right or y1 <= top or y0 >= bottom:
                visibility = "hidden"
            elif visibility == "painted" and (x0 < left or y0 < top or x1 > right or y1 > bottom):
                visibility = "unverified"
            attributes["paint_visibility"] = visibility
        return attributes
