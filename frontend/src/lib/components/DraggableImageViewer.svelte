<script lang="ts">
	import { X, GripHorizontal } from 'lucide-svelte';
	
	interface Props {
		selectedImage: { src: string; alt: string } | null;
	}

	let { selectedImage = $bindable() }: Props = $props();

	let isDragging = $state(false);
	let isResizing = $state(false);
	let dragStart = $state({ x: 0, y: 0 });
	let position = $state({ x: 100, y: 100 });
	let size = $state({ width: 400, height: 300 });
	let containerRef: HTMLDivElement;

	function closeViewer() {
		selectedImage = null;
	}

	function handleMouseDown(e: MouseEvent) {
		if (e.target === containerRef || (e.target as HTMLElement).classList.contains('drag-handle')) {
			isDragging = true;
			dragStart = { x: e.clientX - position.x, y: e.clientY - position.y };
			e.preventDefault();
		}
	}

	function handleResizeMouseDown(e: MouseEvent) {
		isResizing = true;
		dragStart = { x: e.clientX, y: e.clientY };
		e.preventDefault();
		e.stopPropagation();
	}

	function handleMouseMove(e: MouseEvent) {
		if (isDragging) {
			position = {
				x: Math.max(-size.width + 100, Math.min(window.innerWidth - 200, e.clientX - dragStart.x)),
				y: Math.max(0, Math.min(window.innerHeight - 100, e.clientY - dragStart.y))
			};
		} else if (isResizing) {
			const deltaX = e.clientX - dragStart.x;
			const deltaY = e.clientY - dragStart.y;
			size = {
				width: Math.max(200, Math.min(window.innerWidth - position.x - 20, size.width + deltaX)),
				height: Math.max(150, Math.min(window.innerHeight - position.y - 20, size.height + deltaY))
			};
			dragStart = { x: e.clientX, y: e.clientY };
		}
	}

	function handleMouseUp() {
		isDragging = false;
		isResizing = false;
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			closeViewer();
		}
	}

	// Add global event listeners
	$effect(() => {
		document.addEventListener('mousemove', handleMouseMove);
		document.addEventListener('mouseup', handleMouseUp);
		document.addEventListener('keydown', handleKeydown);

		return () => {
			document.removeEventListener('mousemove', handleMouseMove);
			document.removeEventListener('mouseup', handleMouseUp);
			document.removeEventListener('keydown', handleKeydown);
		};
	});
</script>

<!-- Image Container -->
<div
	bind:this={containerRef}
	class="absolute bg-white rounded-lg shadow-2xl border border-gray-300 z-[10000]"
	class:cursor-move={isDragging}
	style="left: {position.x}px; top: {position.y}px; width: {size.width}px; height: {size.height}px;"
	onmousedown={handleMouseDown}
	onclick={(e) => e.stopPropagation()}
	onkeydown={(e) => e.stopPropagation()}
	role="dialog"
	tabindex="0"
>
	<!-- Header with close button -->
	<div
		class="drag-handle flex justify-between items-center p-2 bg-gray-100 rounded-t-lg cursor-move"
	>
		<span class="text-sm font-medium text-gray-700 truncate">{selectedImage?.alt}</span>
		<button
			onclick={closeViewer}
			class="text-gray-500 hover:text-gray-700 p-1 rounded hover:bg-gray-200"
			title="Close (Esc)"
			aria-label="Close"
		>
			<X class="w-4 h-4" />
		</button>
	</div>

	<!-- Image -->
	<div class="p-2 overflow-hidden" style="height: calc(100% - 40px);">
		<img
			src={selectedImage?.src}
			alt={selectedImage?.alt}
			class="w-full h-full object-contain"
			draggable="false"
		/>
	</div>

	<!-- Resize handle -->
	<div
		class="absolute bottom-0 right-0 w-4 h-4 cursor-nw-resize"
		onmousedown={handleResizeMouseDown}
		role="button"
		tabindex="0"
		aria-label="Resize"
	>
		<GripHorizontal class="w-4 h-4 text-gray-400 rotate-45" />
	</div>
</div>
