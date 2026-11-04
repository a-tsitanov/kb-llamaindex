// Brand occupants for the web client's brand slots (same factory format as
// the official ui-brand-official client bundle). The BRAND_NAME constant below
// is a placeholder filled at image build time from BRAND_NAME.
window.__ModuleLoader__.load({
	id: "kb-brand",
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
		let react_jsx_runtime = require("react/jsx-runtime");
		const BRAND_NAME = "__BRAND_NAME__";
		/** Portrait mark: a framed bust on a rounded square (paths only, no font
		 * dependency; same geometry as brand/favicon-*.svg). */
		const MARK_PATH = "M9.5 5h13A3.5 3.5 0 0 1 26 8.5v15a3.5 3.5 0 0 1-3.5 3.5h-13A3.5 3.5 0 0 1 6 23.5v-15A3.5 3.5 0 0 1 9.5 5zm0 2A1.5 1.5 0 0 0 8 8.5v15A1.5 1.5 0 0 0 9.5 25h13a1.5 1.5 0 0 0 1.5-1.5v-15A1.5 1.5 0 0 0 22.5 7zM16 9.5a3.5 3.5 0 1 1 0 7 3.5 3.5 0 0 1 0-7zM9.75 25v-.75c0-3.4 2.8-5.5 6.25-5.5s6.25 2.1 6.25 5.5V25z";
		function KbBrandMark({ size, className }) {
			const s = size ?? 24;
			return (0, react_jsx_runtime.jsxs)("svg", {
				width: s,
				height: s,
				viewBox: "0 0 32 32",
				className,
				role: "img",
				"aria-label": BRAND_NAME,
				children: [
					(0, react_jsx_runtime.jsx)("rect", { x: 1, y: 1, width: 30, height: 30, rx: 7, fill: "#4f46e5" }),
					(0, react_jsx_runtime.jsx)("path", { d: MARK_PATH, fill: "#ffffff", fillRule: "evenodd" })
				]
			});
		}
		/** Brand name text next to the sidebar mark. */
		function KbBrandName() {
			return (0, react_jsx_runtime.jsx)("span", {
				style: { fontWeight: 600, fontSize: 15, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" },
				children: BRAND_NAME
			});
		}
		/** Required service: the UI slot registry. */
		const inject = ["slots"];
		function apply(ctx) {
			ctx.slots.inject("sidebar.brand.mark", () => ctx.slots.inject("sidebar.brand.name", function* () {
				yield ctx.slots.register({ name: "sidebar.brand.mark" }, KbBrandMark);
				yield ctx.slots.register({ name: "sidebar.brand.name" }, KbBrandName);
			}));
			ctx.slots.inject("conversation.hero.brand.mark", function* () {
				yield ctx.slots.register({ name: "conversation.hero.brand.mark" }, KbBrandMark);
			});
		}
		exports.apply = apply;
		exports.inject = inject;
		return module.exports;
	}
});
