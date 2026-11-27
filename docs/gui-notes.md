# Interface notes

What changed in the GUI while the screenshots in [`walkthrough.md`](walkthrough.md)
were being taken, and what is still rough. Nothing here touches the solver —
`gridfin/lattice.py` and `gridfin/cad.py` are untouched, and the 551 tests pass
unchanged.

## Changed

**The lattice size field had no label.** `addRow("", self.size_stack)` put a bare
spin box under *Size by* showing `10`, or `0.2000 m`, with nothing to say which.
It now has a label that follows the *Size by* dropdown.

**Each thickness showed its value twice.** A dropdown reading `20 mm` sat next to
a greyed-out spin box reading `20.00 mm` — the same number, one copy dead, about
110 px of width. The millimetre box now appears only when you pick `Custom...`.

**An unsolvable design blanked the preview.** `ax.clear()` with nothing drawn
after it left an empty 0–1 matplotlib axes with default ticks, which reads as a
crash rather than as a refusal. It now prints the reason in the preview area, and
the status bar carries it too.

**A failed solve left the old fits rows on screen.** The early return skipped
`_update_fits`, so the table still listed candidates for the previous inputs and
double-clicking one applied a cell count derived from a design that no longer
existed. The table is now cleared.

**Only `ValueError` was caught.** From PySide6 6.5 an unhandled Python exception
in a slot aborts the process, so anything `solve()` raised other than `ValueError`
— while you were typing, in the debounced refresh — would take the window down
with a traceback on stderr. The handler now catches `Exception` and shows the
message. `ValueError` is still what the solver raises deliberately, and its
messages still read as intended.

**The readout was one run-on paragraph** of seven facts separated by `|` and
`&nbsp;`. It is now a label/value table, so the numbers line up in a column and
the clean/not-clean verdict sits on its own line at the bottom.

**The fits table needed scrolling to see its own answer.** Nine candidate rows in
a viewport about six rows tall, and the green best-fit row — the single most
useful thing in the table — was often the one below the fold. Rows are now 20 px
with a 206 px minimum height, so all nine fit.

**Nothing said what bold and green meant** in that table, or what the two colour
swatches above the preview were. Both now have a one-line legend, and the
swatches read *edge (half)* and *corner (quarter)* rather than *edge* and
*corner*.

**The matplotlib toolbar carried Subplots and Customize.** Both are meaningless
for a single auto-fitted axes — one opens margin sliders for a layout that
`tight_layout()` immediately overwrites, the other a curve-style editor for a
plot with no curves. Pan, zoom, home and save are kept.

**The preview wasted a quarter of its width on margin.** `m = 0.25 * max(b, h)`
on each side. The dimension arrows and their labels need about 0.135, so it is
now 0.18 with dimensions on and 0.06 with them off.

**Small things.** `deg` → `°`, `kg/m3` → `kg/m³`, `m2` → `m²`, `dh` → `Δh`. The
window title carries the design name. The status bar showed `ready` forever and
now shows the solved summary. *Mirror top/bottom* only had a tooltip while it was
disabled, which is the one state where a tooltip is hardest to find a reason for;
both states now explain themselves, and so does the chamfer-leg box when square
corners grey it out.

## Still rough

**The left column scrolls, and the fold lands mid-group.** At 900 px high the
*Material / hinge* group is cut through its own title and *CFD domain* is out of
sight entirely. Those two are set-once settings competing for space with the ones
you change every minute. Tabs, or folding them into an *Advanced* section, would
remove the scrolling altogether — but it is a layout restructure, so it is not in
this pass.

**`Size by` plus a dynamic label is two rows saying one thing.** Showing cells
across span and target pitch as two always-visible fields that update each other
would drop the dropdown and show both numbers at once, which is closer to how you
actually think about it.

**Nothing accepts the snapped height.** The baseline sits at `h = 3.610 m` with
the target still reading `3.500`, and *Save design* stores the stale target. A
button to pull the solved height into the target field would close that loop.

**`x_h`, `z_h` and the CFD domain multiples have no visible effect.** They are
recorded into the JSON and used by the fluid domain, but nothing in the preview
moves when you change them, so a wrong value is easy to set and hard to notice.
Drawing the hinge point, and the domain extents as a labelled outline, would fix
that.

**Each export leaves its finished `QThread` behind.** `self._thread = QThread(self)`
parents it to the window, so replacing the attribute drops the Python reference
but not the C++ object: one finished thread accumulates per export. Harmless at
the scale anyone exports by hand, worth tidying if export ever becomes
cancellable or scripted.

**`Frame t_f` and `S_ref` read as code in a UI.** Left as they are deliberately —
they match the variable list in the README and the keys in the exported JSON, and
breaking that match to gain a prettier label is the worse trade.

## Reproducing the images

The GUI screenshots come from [`make_screenshots.py`](make_screenshots.py),
which drives the real window, so they follow the layout rather than drifting from
it:

```bash
xvfb-run -a --server-args="-screen 0 1600x1000x24" python3 docs/make_screenshots.py
```

The two 3D line drawings are cadquery's SVG exporter over `fin_solid()`, viewed
along `projectionDir=(1, -0.55, 0.40)` with hidden lines off, then rasterised in
a browser and cropped to the drawing — `fin-corner.png` is the bottom-left corner
of the same render rather than a separate cut, so there are no cut artefacts in
it.
