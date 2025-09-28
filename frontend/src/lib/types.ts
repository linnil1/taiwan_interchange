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

export interface WikiData {
	/** Wikipedia interchange name */
	name: string;
	/** Exit text like "0 左營端" */
	exit_text: string;
	/** Distance in kilometers as string */
	km_distance: string;
	/** Region or area */
	region: string;
	/** Forward/southbound direction destinations */
	forward_direction: string[];
	/** Reverse/northbound direction destinations */
	reverse_direction: string[];
	/** Types of interchange */
	interchange_type: string[];
	/** Opening dates */
	opening_date: string[];
	/** Connecting roads */
	connecting_roads: string[];
	/** Wikipedia URL where this data came from (highway page) */
	url: string;
	/** Wikipedia URL for interchange-specific page (if exists) */
	interchange_url: string;
}

export interface GovData {
	/** Government data interchange name */
	name: string;
	/** Distance in kilometers as string */
	km_distance: string;
	/** Service area facilities */
	service_area: string[];
	/** Southbound exit information */
	southbound_exit: string[];
	/** Northbound exit information */
	northbound_exit: string[];
	/** Eastbound exit information */
	eastbound_exit: string[];
	/** Westbound exit information */
	westbound_exit: string[];
	/** Additional notes */
	notes: string[];
	/** Type of facility (interchange, service_area, rest_stop, other) */
	facility_type: string;
	/** Highway page URL */
	url: string;
	/** Specific interchange diagram URL */
	interchange_url: string;
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
	/** Wikipedia data if available */
	wikis: WikiData[];
	/** Government data if available */
	govs: GovData[];
	/** Wikidata IDs from OSM motorway_junction nodes */
	wikidata_ids: string[];
}

// Utility types for API responses
export type InterchangeList = Interchange[];

// Type guards for runtime type checking
export function isNode(obj: unknown): obj is Node {
	return (
		typeof obj === 'object' &&
		obj !== null &&
		typeof (obj as Node).lat === 'number' &&
		typeof (obj as Node).lng === 'number' &&
		typeof (obj as Node).id === 'number'
	);
}

export function isPath(obj: unknown): obj is Path {
	return (
		typeof obj === 'object' &&
		obj !== null &&
		typeof (obj as Path).id === 'number' &&
		typeof (obj as Path).part === 'number' &&
		Array.isArray((obj as Path).nodes) &&
		(obj as Path).nodes.every(isNode)
	);
}

export function isRamp(obj: unknown): obj is Ramp {
	return (
		typeof obj === 'object' &&
		obj !== null &&
		typeof (obj as Ramp).id === 'number' &&
		Array.isArray((obj as Ramp).destination) &&
		(obj as Ramp).destination.every(
			(d: unknown) =>
				typeof d === 'object' &&
				d !== null &&
				typeof (d as Destination).id === 'number' &&
				typeof (d as Destination).name === 'string' &&
				typeof (d as Destination).destination_type === 'string' &&
				typeof (d as Destination).road_type === 'string' &&
				typeof (d as Destination).relation_type === 'string'
		) &&
		Array.isArray((obj as Ramp).from_ramps) &&
		Array.isArray((obj as Ramp).to_ramps) &&
		Array.isArray((obj as Ramp).paths) &&
		(obj as Ramp).paths.every(isPath)
	);
}

export function isBounds(obj: unknown): obj is Bounds {
	return (
		typeof obj === 'object' &&
		obj !== null &&
		typeof (obj as Bounds).min_lat === 'number' &&
		typeof (obj as Bounds).max_lat === 'number' &&
		typeof (obj as Bounds).min_lng === 'number' &&
		typeof (obj as Bounds).max_lng === 'number'
	);
}

export function isRelation(obj: unknown): obj is Relation {
	return (
		typeof obj === 'object' &&
		obj !== null &&
		typeof (obj as Relation).id === 'number' &&
		typeof (obj as Relation).name === 'string' &&
		typeof (obj as Relation).road_type === 'string' &&
		typeof (obj as Relation).relation_type === 'string'
	);
}

export function isWikiData(obj: unknown): obj is WikiData {
	return (
		typeof obj === 'object' &&
		obj !== null &&
		typeof (obj as WikiData).name === 'string' &&
		typeof (obj as WikiData).exit_text === 'string' &&
		typeof (obj as WikiData).km_distance === 'string' &&
		typeof (obj as WikiData).region === 'string' &&
		Array.isArray((obj as WikiData).forward_direction) &&
		Array.isArray((obj as WikiData).reverse_direction) &&
		Array.isArray((obj as WikiData).interchange_type) &&
		Array.isArray((obj as WikiData).opening_date) &&
		Array.isArray((obj as WikiData).connecting_roads) &&
		typeof (obj as WikiData).url === 'string'
	);
}

export function isGovData(obj: unknown): obj is GovData {
	return (
		typeof obj === 'object' &&
		obj !== null &&
		typeof (obj as GovData).name === 'string' &&
		typeof (obj as GovData).km_distance === 'string' &&
		Array.isArray((obj as GovData).service_area) &&
		Array.isArray((obj as GovData).southbound_exit) &&
		Array.isArray((obj as GovData).northbound_exit) &&
		Array.isArray((obj as GovData).eastbound_exit) &&
		Array.isArray((obj as GovData).westbound_exit) &&
		Array.isArray((obj as GovData).notes) &&
		typeof (obj as GovData).facility_type === 'string' &&
		typeof (obj as GovData).url === 'string'
	);
}

export function isInterchange(obj: unknown): obj is Interchange {
	return (
		typeof obj === 'object' &&
		obj !== null &&
		typeof (obj as Interchange).id === 'number' &&
		typeof (obj as Interchange).name === 'string' &&
		isBounds((obj as Interchange).bounds) &&
		Array.isArray((obj as Interchange).ramps) &&
		(obj as Interchange).ramps.every(isRamp) &&
		Array.isArray((obj as Interchange).refs) &&
		(obj as Interchange).refs.every(isRelation) &&
		Array.isArray((obj as Interchange).wikis) &&
		(obj as Interchange).wikis.every(isWikiData) &&
		Array.isArray((obj as Interchange).govs) &&
		(obj as Interchange).govs.every(isGovData) &&
		Array.isArray((obj as Interchange).wikidata_ids) &&
		(obj as Interchange).wikidata_ids.every((id: unknown) => typeof id === 'string')
	);
}
