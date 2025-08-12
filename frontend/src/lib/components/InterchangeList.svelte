<script lang="ts">
	import type { Interchange } from '$lib/types.js';

	let {
		interchanges = [],
		searchTerm = '',
		selectedInterchange = null,
		onSelectInterchange
	}: {
		interchanges: Interchange[];
		searchTerm: string;
		selectedInterchange: Interchange | null;
		onSelectInterchange: (interchange: Interchange) => void;
	} = $props();

	function handleInterchangeClick(interchange: Interchange) {
		onSelectInterchange(interchange);
	}
</script>

<div class="h-full overflow-y-auto bg-white">
	<div class="bg-gray-100 p-3 border-b border-gray-300 font-bold sticky top-0">
		Interchanges
		{#if searchTerm}
			(filtered: {interchanges.length})
		{:else}
			({interchanges.length})
		{/if}
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
				onclick={() => handleInterchangeClick(interchange)}
				role="button"
				tabindex="0"
				onkeydown={(e) => e.key === 'Enter' && handleInterchangeClick(interchange)}
			>
				<div>
					<div class="font-medium text-gray-800">{interchange.name}</div>
					<div class="text-xs text-gray-600 mt-1">
						Bounds: {interchange.bounds.min_lat.toFixed(4)}, {interchange.bounds.min_lng.toFixed(4)}
						to {interchange.bounds.max_lat.toFixed(4)}, {interchange.bounds.max_lng.toFixed(4)}
					</div>
				</div>
				<div class="bg-blue-500 text-white px-2 py-1 rounded-full text-xs font-bold">
					{interchange.ramps.length}
				</div>
			</div>
		{/each}
	{/if}
</div>
