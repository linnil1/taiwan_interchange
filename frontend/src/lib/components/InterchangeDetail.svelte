<script lang="ts">
	import type { Interchange } from '$lib/types.js';

	let {
		interchange,
		onClose,
		selectedRampIndex = $bindable(null)
	}: {
		interchange: Interchange;
		onClose: () => void;
		selectedRampIndex?: number | null;
	} = $props();

	let rampElements: HTMLElement[] = [];

	// Scroll to selected ramp when selectedRampIndex changes
	$effect(() => {
		if (selectedRampIndex !== null && rampElements[selectedRampIndex]) {
			rampElements[selectedRampIndex].scrollIntoView({
				behavior: 'smooth',
				block: 'center'
			});
		}
	});

	function selectRamp(rampIndex: number) {
		selectedRampIndex = selectedRampIndex === rampIndex ? null : rampIndex;
	}
</script>

<div class="w-96 bg-white border-r border-gray-300 overflow-y-auto">
	<div class="sticky top-0 bg-white border-b border-gray-300 p-4">
		<div class="flex justify-between items-start">
			<div>
				<h2 class="text-lg font-bold text-gray-800">{interchange.name}</h2>
				<p class="text-sm text-gray-600">{interchange.ramps.length} ramps</p>
			</div>
			<button
				class="px-3 py-1 bg-red-500 text-white text-sm rounded hover:bg-red-600 transition-colors"
				onclick={onClose}
			>
				✕
			</button>
		</div>
	</div>

	<div class="p-4">
		<!-- Bounds Info -->
		<div class="mb-4 p-3 bg-gray-50 rounded text-xs">
			<strong>Bounds:</strong>
			<br />
			Lat: {interchange.bounds.min_lat.toFixed(6)} to {interchange.bounds.max_lat.toFixed(6)}
			<br />
			Lng: {interchange.bounds.min_lng.toFixed(6)} to {interchange.bounds.max_lng.toFixed(6)}
		</div>

		<!-- Ramps List -->
		<div>
			<h3 class="font-semibold text-gray-700 mb-3">Ramps:</h3>
			{#each interchange.ramps as ramp, i}
				<button
					bind:this={rampElements[i]}
					onclick={() => selectRamp(i)}
					class="w-full mb-3 p-3 border rounded transition-all duration-300 cursor-pointer {selectedRampIndex ===
					i
						? 'border-blue-500 bg-blue-50 shadow-md'
						: 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'}"
				>
					<div class="flex justify-between items-start mb-2">
						<span
							class="font-medium text-sm {selectedRampIndex === i
								? 'text-blue-700'
								: ''} flex items-center"
						>
							{ramp.name}
							<span class="ml-2 text-xs text-gray-400">
								{selectedRampIndex === i ? '👁️' : ''}
							</span>
						</span>
						<span class="text-xs text-gray-500"
							>{ramp.paths.length} path{ramp.paths.length === 1 ? '' : 's'}</span
						>
					</div>
					<div class="text-sm text-gray-600 mb-2">
						<strong>To:</strong>
						{ramp.to}
					</div>

					<!-- Paths within ramp -->
					<div class="ml-2">
						{#each ramp.paths as path, j}
							<div class="mb-2 p-2 bg-gray-50 rounded text-xs">
								<div class="flex items-center justify-between mb-1">
									<div class="font-medium text-gray-700">
										Path {j + 1}:
										<a
											href="https://www.openstreetmap.org/way/{path.id}"
											target="_blank"
											rel="noopener noreferrer"
											class="text-blue-600 hover:text-blue-800 underline ml-2"
											onclick={(e) => e.stopPropagation()}
										>
											Way {path.id}
										</a>
										{#if path.part > 0}
											(part {path.part})
										{/if}
									</div>
									<div class="text-gray-600 text-xs">
										{path.nodes.length} nodes
									</div>
								</div>

								<!-- Node IDs - Horizontal layout with left alignment -->
								<div class="text-gray-500 flex items-start">
									<span class="font-medium mr-2 flex-shrink-0">Nodes:</span>
									<div
										class="max-h-16 overflow-y-auto text-xs leading-tight flex-1 flex flex-wrap items-start"
									>
										{#each path.nodes as node, k}
											<a
												href="https://www.openstreetmap.org/node/{node.id}"
												target="_blank"
												rel="noopener noreferrer"
												class="inline-block mr-1 text-blue-600 hover:text-blue-800 underline"
												onclick={(e) => e.stopPropagation()}
											>
												{node.id}
											</a>{k < path.nodes.length - 1 ? ',' : ''}
										{/each}
									</div>
								</div>
							</div>
						{/each}
					</div>
				</button>
			{/each}
		</div>
	</div>
</div>
