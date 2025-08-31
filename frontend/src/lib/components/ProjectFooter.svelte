<script lang="ts">
	import { locales, getLocale, setLocale } from '$lib/paraglide/runtime';
	import * as m from '$lib/paraglide/messages';
	import { Info, Globe, Languages } from 'lucide-svelte';

	function handleLanguageChange(lang: string) {
		setLocale(lang as any);
	}

	const languageNames: Record<string, string> = {
		en: 'English',
		'zh-tw': '繁體中文'
	};

	let showLanguageDropdown = $state(false);
	let currentLocale = $state(getLocale());

	// Update current locale when it changes
	$effect(() => {
		currentLocale = getLocale();
	});
</script>

<div class="border-t border-gray-300 px-3 py-2 bg-gray-50">
	<!-- Project Title Row -->
	<div class="text-xs mb-2 flex gap-x-2 items-center">
		<div class="font-semibold text-gray-800">{m.project_title()}</div>
		<div class="text-gray-600">{m.project_author({ author: 'linnil1' })}</div>
	</div>

	<!-- Language and About Row -->
	<div class="flex items-center justify-between">
		<!-- Language Switcher -->
		<div class="relative">
			<button
				onclick={() => (showLanguageDropdown = !showLanguageDropdown)}
				class="flex items-center gap-1 px-2 py-1 text-xs text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded transition-colors"
				aria-label={m.language()}
			>
				<Languages size={12} />
				<span>{languageNames[currentLocale] || currentLocale}</span>
				<svg class="w-3 h-3 ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"
					></path>
				</svg>
			</button>

			{#if showLanguageDropdown}
				<!-- svelte-ignore a11y_click_events_have_key_events -->
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<div
					class="absolute bottom-full left-0 mb-1 bg-white border border-gray-200 rounded-md shadow-lg z-50 min-w-[120px]"
					onclick={(e) => e.stopPropagation()}
				>
					{#each locales as lang}
						<button
							onclick={() => {
								handleLanguageChange(lang);
								showLanguageDropdown = false;
							}}
							class="w-full text-left px-3 py-2 text-xs hover:bg-gray-100 transition-colors flex items-center gap-2
								{currentLocale === lang ? 'bg-blue-50 text-blue-600' : 'text-gray-700'}"
						>
							<Globe size={12} />
							{languageNames[lang] || lang}
							{#if currentLocale === lang}
								<svg class="w-3 h-3 ml-auto" fill="currentColor" viewBox="0 0 20 20">
									<path
										fill-rule="evenodd"
										d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
										clip-rule="evenodd"
									></path>
								</svg>
							{/if}
						</button>
					{/each}
				</div>
			{/if}
		</div>

		<!-- About Button -->
		<a
			href="/about"
			class="px-2 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors flex items-center gap-1 text-xs"
		>
			<Info size={12} />
			{m.about()}
		</a>
	</div>
</div>

<!-- Click outside to close dropdown -->
{#if showLanguageDropdown}
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="fixed inset-0 z-40" onclick={() => (showLanguageDropdown = false)}></div>
{/if}
