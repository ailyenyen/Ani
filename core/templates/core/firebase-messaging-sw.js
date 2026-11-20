/* Firebase Cloud Messaging service worker: shows Ani price alerts when the site is closed. */
self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  const link = new URL(event.notification.data?.link || "/alerts/", self.location.origin);
  event.waitUntil(clients.openWindow(link.origin === self.location.origin ? link.href : "/alerts/"));
});

importScripts("https://www.gstatic.com/firebasejs/10.12.2/firebase-app-compat.js");
importScripts("https://www.gstatic.com/firebasejs/10.12.2/firebase-messaging-compat.js");

firebase.initializeApp({{ firebase_config|safe }});
const messaging = firebase.messaging();

messaging.onBackgroundMessage(function (payload) {
  const note = payload.data || {};
  return self.registration.showNotification(note.title || "Ani price alert", {
    body: note.body || "",
    data: { link: note.link || "/alerts/" }
  });
});
