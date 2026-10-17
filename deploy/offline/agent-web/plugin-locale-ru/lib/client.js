// Russian language pack for the agent web UI. Registers locale "ru" (fallback
// "en": keys missing here show in English) and one "ru" dictionary per dsh
// locale namespace. Russian is the default when the user has not chosen a
// language; an explicit choice in Settings → General → Language still wins.
// The dictionary lives in ../ru.json (edit there); the image build inlines it
// into the placeholder below (brand/rebrand.mjs).
window.__ModuleLoader__.load({
	id: "kb-locale-ru",
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
		const RU = __RU_DICT__;
		const inject = ["locale"];
		function apply(ctx) {
			const locale = ctx.locale;
			const disposers = [locale.addLanguage({ id: "ru", label: "Русский", fallback: "en" })];
			for (const [ns, dict] of Object.entries(RU)) disposers.push(locale.register(ns, "ru", dict));
			// Default language: "provisional" is what stands while no stored
			// preference exists (normally browser-derived, else English).
			locale.provisional = "ru";
			if (locale.preference === void 0 && locale.getSnapshot().active !== "ru") locale.publish("ru", true);
			ctx.effect(() => () => {
				for (const dispose of disposers.reverse()) dispose();
			}, "kb-locale-ru: language pack");
		}
		exports.apply = apply;
		exports.inject = inject;
		return module.exports;
	}
});
