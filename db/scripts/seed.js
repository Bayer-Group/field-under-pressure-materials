// Seed script for Field Under Pressure (Hackathon GEO — Crop Science)
// Creates required MongoDB collections with ObjectId (_id) validation only.
// Does NOT insert any synthetic/dummy documents or extra schema fields.

const COLLECTIONS = [
  'User',
  'Orchard',
  'Tree',
  'CropPref',
  'Preferences',
  'Geofence',
  'JobSchedule',
  'JobLog',
  'ManualControl',
];

const DEFAULT_DB_NAME = 'field_under_pressure';

const envDbName =
  typeof process !== 'undefined' && process.env
    ? process.env.MONGO_DB || process.env.MONGO_INITDB_DATABASE
    : null;

const currentDbName = db.getName();
const dbName =
  envDbName ||
  (currentDbName && currentDbName !== 'test' && currentDbName !== 'admin'
    ? currentDbName
    : DEFAULT_DB_NAME);

const targetDb = db.getSiblingDB(dbName);

const objectIdOnlyValidator = {
  $jsonSchema: {
    bsonType: 'object',
    required: ['_id'],
    properties: {
      _id: {
        bsonType: 'objectId',
        description: 'Primary ObjectId identifier',
      },
    },
  },
};

const existingCollections = new Set(targetDb.getCollectionNames());

print(`[seed] Target database: ${dbName}`);

let createdCount = 0;
let skippedCount = 0;

for (const collectionName of COLLECTIONS) {
  if (existingCollections.has(collectionName)) {
    print(`[seed] Collection "${collectionName}" already exists — skipping.`);
    skippedCount += 1;
    continue;
  }

  targetDb.createCollection(collectionName, {
    validator: objectIdOnlyValidator,
    validationLevel: 'strict',
    validationAction: 'error',
  });
  print(`[seed] Created empty collection "${collectionName}" (_id: ObjectId).`);
  createdCount += 1;
}

print(
  `[seed] Done. Created: ${createdCount}, already existed: ${skippedCount}, total expected: ${COLLECTIONS.length}.`
);
