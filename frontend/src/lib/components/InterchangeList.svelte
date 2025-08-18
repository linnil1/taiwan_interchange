<script lang="ts">
	import type { Interchange } from '$lib/types.js';

	// Svelte 5 runes: props + bindable local state for search
	let {
		interchanges = [],
		selectedInterchange = null,
		onSelectInterchange,
		searchTerm = $bindable('')
	} = $props<{
		interchanges: Interchange[];
		selectedInterchange: Interchange | null;
		onSelectInterchange: (interchange: Interchange) => void;
		searchTerm: string;
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
	<div class="bg-gray-100 p-3 border-b border-gray-300 sticky top-0">
		<div class="font-bold">
			Interchanges {searchTerm ? `(filtered: ${interchanges.length})` : `(${interchanges.length})`}
		</div>
		<input
			class="mt-2 w-full rounded border border-gray-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
			type="search"
			placeholder="Search by name or #id"
			bind:value={searchTerm}
		/>
	</div>

	{#if interchanges.length === 0}
		{#if searchTerm}
			<div class="p-5 text-center text-gray-600 italic">
				No interchanges found matching "{searchTerm}"
			</div>
		{:else}
			<div class="p-5 text-center text-gray-600">Loading interchanges...</div>
		{/if}
	{:else}
		{#each interchanges as interchange}
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
				<div>
					<div class="font-medium text-gray-800">#{interchange.id} {interchange.name}</div>
				</div>
			</div>
		{/each}
	{/if}
</div>
