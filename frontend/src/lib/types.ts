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

export const enum DestinationType {
	EXIT = 'EXIT',
	ENTER = 'ENTER',
	OSM = 'OSM'
}

export const enum RelationType {
	RELATION = 'RELATION',
	WAY = 'WAY',
	NODE = 'NODE'
}

export const enum RoadType {
	FREEWAY = 'freeway',
	PROVINCIAL = 'provincial',
	NORMAL = 'normal',
	WEIGH = 'weigh',
	WAY = 'way',
	JUNCTION = 'junction',
	DESTINATION = 'destination'
}

export interface Destination {
	/** OSM relation ID */
	id: number;
	name: string;
	destination_type: DestinationType;
	/** Type of road relation */
	road_type: RoadType;
	/** Type of OSM relation */
	relation_type: RelationType;
}

export interface Ramp {
	/** Unique identifier for the ramp */
	id: number;
	/** Destination(s) that this ramp leads to */
	destination: Destination[];
	/** Source ramp IDs that connect to this ramp */
	from_ramps: number[];
	/** Target ramp IDs that this ramp connects to */
	to_ramps: number[];
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

export interface Relation {
	/** OSM relation ID */
	id: number;
	/** Name of the relation */
	name: string;
	/** Type of road relation */
	road_type: RoadType;
	/** Type of OSM relation */
	relation_type: RelationType;
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
	/** Freeway route_master relations that this interchange belongs to */
	refs: Relation[];
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
		Array.isArray(obj.destination) &&
		obj.destination.every(
			(d: any) =>
				typeof d?.id === 'number' &&
				typeof d?.name === 'string' &&
				typeof d?.destination_type === 'string' &&
				typeof d?.road_type === 'string' &&
				typeof d?.relation_type === 'string'
		) &&
		Array.isArray(obj.from_ramps) &&
		Array.isArray(obj.to_ramps) &&
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

export function isRelation(obj: any): obj is Relation {
	return (
		typeof obj === 'object' &&
		typeof obj.id === 'number' &&
		typeof obj.name === 'string' &&
		typeof obj.road_type === 'string' &&
		typeof obj.relation_type === 'string'
	);
}

export function isInterchange(obj: any): obj is Interchange {
	return (
		typeof obj === 'object' &&
		typeof obj.id === 'number' &&
		typeof obj.name === 'string' &&
		isBounds(obj.bounds) &&
		Array.isArray(obj.ramps) &&
		obj.ramps.every(isRamp) &&
		Array.isArray(obj.refs) &&
		obj.refs.every(isRelation)
	);
}
