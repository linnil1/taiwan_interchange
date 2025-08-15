/**
 * TypeScript interfaces that match the Python Pydantic models
 * These should be kept in sync with backend/data.py
 */

export interface Node {
	/** Latitude coordinate */
	lat: number;
	/** Longitude coordinate */
	lng: number;
	/** Node ID from OpenStreetMap */
	id: number;
}

export interface Path {
	/** Way ID from OpenStreetMap */
	id: number;
	/** Part number when a way is broken into multiple paths */
	part: number;
	/** Array of nodes that make up this path */
	nodes: Node[];
}

export interface Ramp {
	/** Unique identifier for the ramp */
	id: number;
	/** Destination(s) that this ramp leads to */
	to: string[];
	/** Array of connected paths that form this ramp */
	paths: Path[];
}

export interface Bounds {
	/** Minimum latitude */
	min_lat: number;
	/** Maximum latitude */
	max_lat: number;
	/** Minimum longitude */
	min_lng: number;
	/** Maximum longitude */
	max_lng: number;
}

export interface Interchange {
	/** Unique identifier for the interchange */
	id: number;
	/** Name of the interchange */
	name: string;
	/** Geographical bounds of the interchange */
	bounds: Bounds;
	/** Array of ramps in this interchange */
	ramps: Ramp[];
}

// Utility types for API responses
export type InterchangeList = Interchange[];

// Type guards for runtime type checking
export function isNode(obj: any): obj is Node {
	return (
		typeof obj === 'object' &&
		typeof obj.lat === 'number' &&
		typeof obj.lng === 'number' &&
		typeof obj.id === 'number'
	);
}

export function isPath(obj: any): obj is Path {
	return (
		typeof obj === 'object' &&
		typeof obj.id === 'number' &&
		typeof obj.part === 'number' &&
		Array.isArray(obj.nodes) &&
		obj.nodes.every(isNode)
	);
}

export function isRamp(obj: any): obj is Ramp {
	return (
		typeof obj === 'object' &&
		typeof obj.id === 'number' &&
		Array.isArray(obj.to) &&
		Array.isArray(obj.paths) &&
		obj.paths.every(isPath)
	);
}

export function isBounds(obj: any): obj is Bounds {
	return (
		typeof obj === 'object' &&
		typeof obj.min_lat === 'number' &&
		typeof obj.max_lat === 'number' &&
		typeof obj.min_lng === 'number' &&
		typeof obj.max_lng === 'number'
	);
}

export function isInterchange(obj: any): obj is Interchange {
	return (
		typeof obj === 'object' &&
		typeof obj.id === 'number' &&
		typeof obj.name === 'string' &&
		isBounds(obj.bounds) &&
		Array.isArray(obj.ramps) &&
		obj.ramps.every(isRamp)
	);
}
