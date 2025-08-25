<script lang="ts">
	import type { Interchange } from '$lib/types.js';

	let {
		interchange,
		onClose,
		selectedRampIndex = $bindable(null),
		onFitToRamp
	}: {
		interchange: Interchange;
		onClose: () => void;
		selectedRampIndex?: number | null;
		onFitToRamp?: (rampIndex: number) => void;
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

	function navigateToRamp(rampId: number) {
		const rampIndex = interchange.ramps.findIndex((r) => r.id === rampId);
		if (rampIndex !== -1) {
			selectedRampIndex = rampIndex;
		}
	}

	// Helper function to get ramp connections within this interchange
	function getRampConnections(ramp: any) {
		const fromRamps = ramp.from_ramps
			.map((id: number) => interchange.ramps.find((r) => r.id === id))
			.filter((r: any) => r !== undefined);

		const toRamps = ramp.to_ramps
			.map((id: number) => interchange.ramps.find((r) => r.id === id))
			.filter((r: any) => r !== undefined);

		return { fromRamps, toRamps };
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
				<div
					bind:this={rampElements[i]}
					role="button"
					tabindex="0"
					onkeydown={(e) => {
						if (e.key === 'Enter' || e.key === ' ') {
							e.preventDefault();
							selectRamp(i);
						}
					}}
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
							Ramp {ramp.id}
							<span class="ml-2 text-xs text-gray-400">
								{selectedRampIndex === i ? '👁️' : ''}
							</span>
							{#if selectedRampIndex === i && onFitToRamp}
								<button
									type="button"
									class="ml-2 text-blue-500 hover:text-blue-700 transition-colors"
									onclick={(e) => {
										e.stopPropagation();
										onFitToRamp(i);
									}}
									title="Zoom to ramp"
								>
									🔍
								</button>
							{/if}
						</span>
						<span class="text-xs text-gray-500"
							>{ramp.paths.length} path{ramp.paths.length === 1 ? '' : 's'}</span
						>
					</div>
					<!-- Ramp Navigation -->
					{#if getRampConnections(ramp).fromRamps.length > 0 || getRampConnections(ramp).toRamps.length > 0}
						{@const connections = getRampConnections(ramp)}
						<div class="mb-2 text-xs flex flex-wrap gap-1 mt-1 items-center">
							{#each connections.fromRamps as fromRamp}
								<button
									type="button"
									class="px-2 py-1 bg-green-500 text-white rounded hover:bg-green-600 transition-colors"
									onclick={(e) => {
										e.stopPropagation();
										navigateToRamp(fromRamp.id);
									}}
								>
									← Ramp {fromRamp.id}
								</button>
							{/each}
							{#each connections.toRamps as toRamp}
								<button
									type="button"
									class="px-2 py-1 bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors"
									onclick={(e) => {
										e.stopPropagation();
										navigateToRamp(toRamp.id);
									}}
								>
									Ramp {toRamp.id} →
								</button>
							{/each}
						</div>
					{/if}

					<div class="text-sm text-gray-600 mb-2">
						<strong>To:</strong>
						{#if ramp.destination.length > 0}
							{#each ramp.destination as d, di}
								<span class="inline-flex items-center mr-2">
									<span
										class="px-1.5 py-0.5 rounded text-white text-[10px] mr-1 {d.type === 'ENTER'
											? 'bg-blue-500'
											: 'bg-green-600'}">{d.type}</span
									>
									{d.name}{di < ramp.destination.length - 1 ? ',' : ''}
								</span>
							{/each}
						{:else}
							Unknown
						{/if}
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
				</div>
			{/each}
		</div>
	</div>
</div>
