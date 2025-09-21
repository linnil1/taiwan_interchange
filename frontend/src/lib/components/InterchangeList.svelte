<script lang="ts">
	import type { Interchange } from '$lib/types.js';

	// Svelte 5 runes: props for filtered interchanges
	let {
		interchanges = [],
		selectedInterchange = null,
		onSelectInterchange
	} = $props<{
		interchanges: Interchange[];
		selectedInterchange: Interchange | null;
		onSelectInterchange: (interchange: Interchange) => void;
	}>();

	let listContainer: HTMLDivElement;

	// Scroll to selected interchange when it changes
	$effect(() => {
		if (selectedInterchange && listContainer) {
			// Find the element for the selected interchange
			const selectedElement = listContainer.querySelector(
				`[data-interchange-id="${selectedInterchange.id}"]`
			);
			if (selectedElement) {
				selectedElement.scrollIntoView({
					behavior: 'smooth',
					block: 'center'
				});
			}
		}
	});

	function handleInterchangeClick(interchange: Interchange) {
		onSelectInterchange(interchange);
	}
</script>

<div class="h-full overflow-y-auto bg-white" bind:this={listContainer}>
	{#if interchanges.length === 0}
		<div class="p-5 text-center text-gray-600">Loading interchanges...</div>
	{:else}
		{#each interchanges as interchange (interchange.id)}
			<div
				class="p-3 border-b border-gray-200 cursor-pointer transition-colors duration-200 flex justify-between items-center hover:bg-gray-50 {selectedInterchange &&
				selectedInterchange.id === interchange.id
					? 'bg-blue-50 border-l-4 border-l-blue-500'
					: ''}"
				data-interchange-id={interchange.id}
				onclick={() => handleInterchangeClick(interchange)}
				role="button"
				tabindex="0"
				onkeydown={(e) => e.key === 'Enter' && handleInterchangeClick(interchange)}
			>
				<div class="min-w-0">
					<div class="font-medium text-gray-800 truncate">#{interchange.id} {interchange.name}</div>
					{#if interchange.refs && interchange.refs.length}
						<div class="mt-1 flex flex-wrap gap-1">
							{#each interchange.refs as ref (ref.name)}
								<span
									class="inline-flex items-center rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-700 border border-gray-200"
								>
									{ref.name}
								</span>
							{/each}
						</div>
					{/if}
				</div>
			</div>
		{/each}
	{/if}
</div>
