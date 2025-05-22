function doPost(e) {
  // Parse incoming JSON payload
  var data = JSON.parse(e.postData.contents);
  var docId = data.docId;
  var imageUrl = data.imageUrl;

  // Open the Google Doc by ID
  var doc = DocumentApp.openById(docId);
  var body = doc.getBody();

  // Fetch image from Slack using Bearer token
  var response = UrlFetchApp.fetch(imageUrl, {
    headers: {
      'Authorization': 'Bearer xoxp-'
    }
  });

  // Get the image blob and insert it into the doc
  var imageBlob = response.getBlob();
  body.appendImage(imageBlob);

  return ContentService.createTextOutput("Image inserted");
}
