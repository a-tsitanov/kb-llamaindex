// KB brand occupants for the web client's brand slots (same factory format as
// the official ui-brand-official client bundle). The two string constants below
// are placeholders filled at image build time from BRAND_NAME / BRAND_SHORT.
window.__ModuleLoader__.load({
	id: "kb-brand",
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
		let react_jsx_runtime = require("react/jsx-runtime");
		const BRAND_NAME = "__BRAND_NAME__";
		const BRAND_SHORT = "__BRAND_SHORT__";
		/** Rounded square with the short brand letters. */
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
					(0, react_jsx_runtime.jsx)("rect", { x: 1, y: 1, width: 30, height: 30, rx: 7, fill: "#2563eb" }),
					(0, react_jsx_runtime.jsx)("text", {
						x: 16,
						y: 21.5,
						textAnchor: "middle",
						fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
						fontSize: BRAND_SHORT.length > 2 ? 11 : 15,
						fontWeight: 700,
						fill: "#ffffff",
						children: BRAND_SHORT
					})
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
