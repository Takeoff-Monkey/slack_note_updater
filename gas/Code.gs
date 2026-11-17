// Google Apps Script web app used by the Slack Note Updater bot.
// Deployed with "Execute as: Me (konur@takeoffmonkey.com)" so files it creates
// are owned by a real user — the bot's service account has a 0-byte Drive quota and
// cannot create files itself.
//
// Actions (JSON POST body):
//   { docId, imageUrl }                          -> append Slack image to doc (default)
//   { action: "create_weekly_doc", title }       -> find/create weekly feedback doc

// Weekly feedback reports folder ("Ewing DRFs"). Fixed here, not taken from the
// request, so callers can only ever create docs in this one folder.
var WEEKLY_FEEDBACK_FOLDER_ID = "1UBEbGB2o9Fl_HpRnxx-JJqSDCeq3GWBC";
var WEEKLY_TITLE_PATTERN = /^Ewing Feedback [A-Z][a-z]+ \d{1,2} - ([A-Z][a-z]+ )?\d{1,2}$/;

function doPost(e) {
  var data = JSON.parse(e.postData.contents);

  if (data.action === "create_weekly_doc") {
    return createWeeklyDoc(data.title);
  }
  return insertImage(data.docId, data.imageUrl);
}

function insertImage(docId, imageUrl) {
  var body = DocumentApp.openById(docId).getBody();

  // Fetch image from Slack using Bearer token
  var response = UrlFetchApp.fetch(imageUrl, {
    headers: {
      'Authorization': 'Bearer xoxp-'  // keep the real token from the live script
    }
  });

  body.appendImage(response.getBlob());
  return ContentService.createTextOutput("Image inserted");
}

function createWeeklyDoc(title) {
  if (!title || !WEEKLY_TITLE_PATTERN.test(title)) {
    return json({ ok: false, error: "invalid title" });
  }

  var folder = DriveApp.getFolderById(WEEKLY_FEEDBACK_FOLDER_ID);
  var existing = folder.getFilesByName(title);
  var file;
  if (existing.hasNext()) {
    file = existing.next();
  } else {
    var doc = DocumentApp.create(title);
    file = DriveApp.getFileById(doc.getId());
    file.moveTo(folder);
  }

  return json({ ok: true, id: file.getId(), name: file.getName(), webViewLink: file.getUrl() });
}

function json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
