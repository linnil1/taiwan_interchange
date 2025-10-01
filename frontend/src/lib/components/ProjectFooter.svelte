<script lang="ts">
	import { locales, getLocale, setLocale } from '$lib/paraglide/runtime';
	import * as m from '$lib/paraglide/messages';
	import { Info, Globe, Languages, ChevronDown, Check } from 'lucide-svelte';
	import { resolve } from '$app/paths';

	function handleLanguageChange(lang: string) {
		setLocale(lang as (typeof locales)[number]);
	}

	const languageNames: Record<string, string> = {
		en: 'English',
		'zh-tw': '繁體中文'
	};

	let showLanguageDropdown = $state(false);
	let currentLocale = $derived(getLocale());
</script>

<div class="border-t border-gray-300 px-3 py-2 bg-gray-50 gap-y-1 flex flex-col">
	<!-- Project Title Row -->
	<div class="text-ms font-semibold text-gray-800">{m.project_title()}</div>
	<div class="text-xs text-gray-600">{m.project_author({ author: 'linnil1' })}</div>

	<!-- Language and About Row -->
	<div class="flex items-center justify-between">
		<!-- Language Switcher -->
		<div
			class="relative"
			role="button"
			tabindex="0"
			onmouseenter={() => (showLanguageDropdown = true)}
			onmouseleave={() => (showLanguageDropdown = false)}
		>
			<div
				aria-haspopup="listbox"
				aria-expanded={showLanguageDropdown}
				aria-label={m.language()}
				class="flex items-center gap-1 py-1 text-xs text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded transition-colors cursor-pointer"
			>
				<Languages size={12} />
				<span>{languageNames[currentLocale] || currentLocale}</span>
				<ChevronDown class="w-3 h-3 ml-1" />
			</div>

			{#if showLanguageDropdown}
				<div
					class="absolute bottom-full left-0 bg-white border border-gray-200 rounded-md shadow-lg z-50"
					role="listbox"
				>
					{#each locales as lang (lang)}
						<button
							type="button"
							role="option"
							aria-selected={currentLocale === lang}
							onclick={() => {
								handleLanguageChange(lang);
								showLanguageDropdown = false;
							}}
							class="w-full text-left px-3 py-2 text-xs hover:bg-gray-100 transition-colors flex items-center gap-2 whitespace-nowrap
								{currentLocale === lang ? 'text-blue-600' : 'text-gray-700'}"
						>
							<Globe size={12} />
							{languageNames[lang] || lang}
							{#if currentLocale === lang}
								<Check class="w-3 h-3 ml-auto" />
							{/if}
						</button>
					{/each}
				</div>
			{/if}
		</div>

		<!-- About Button -->
		<a
			href={resolve('/about')}
			class="px-2 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors flex items-center gap-1 text-xs"
		>
			<Info size={12} />
			{m.about()}
		</a>
	</div>
</div>
