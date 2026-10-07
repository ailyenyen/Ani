/* Firebase Cloud Messaging service worker: shows Ani price alerts when the site is closed. */
importScripts("https://www.gstatic.com/firebasejs/10.12.2/firebase-app-compat.js");
importScripts("https://www.gstatic.com/firebasejs/10.12.2/firebase-messaging-compat.js");

firebase.initializeApp({{ firebase_config|safe }});
const messaging = firebase.messaging();

messaging.onBackgroundMessage(function (payload) {
  const note = payload.notification || {};
  self.registration.showNotification(note.title || "Ani price alert", {
    body: note.body || "",
    data: { link: (payload.data && payload.data.link) || "/alerts/" }
  });
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  event.waitUntil(clients.openWindow(event.notification.data.link || "/alerts/"));
});
