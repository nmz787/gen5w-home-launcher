package com.android.launcher3.configurable;

import android.content.*;
import android.content.pm.ActivityInfo;
import android.content.res.*;
import android.graphics.*;
import android.graphics.drawable.*;
import android.os.*;
import android.util.Log;
import android.widget.*;
import org.json.*;
import java.io.*;
import java.lang.reflect.*;
import java.security.MessageDigest;
import java.util.*;

/** API19 extension shared by the OEM launcher and its independent icon editor. */
public final class TileRegistry {
    private static final String TAG = "Gen5wTiles";
    private static final String PACKAGE = "gen5w.configurable";
    private static final File BASE = new File("/data/local/gen5w-home");
    private static final File CONFIG = new File(BASE, "tiles.json");
    private static final int LIMIT = 65536;
    private static List<Tile> tiles = Collections.emptyList();
    private static final Map<Integer, Tile> resources = new HashMap<Integer, Tile>();
    private static final Map<String, Job> jobs = new HashMap<String, Job>();
    private static Context application;
    private static String theme = "auto";

    private TileRegistry() {}

    private static final class Tile {
        String id, name, type;
        ComponentName component;
        String[] argv;
        Bitmap day, night;
        int key;
        boolean toggle;
    }

    private static File imageFile(String path) throws Exception {
        File file = new File(BASE, path).getCanonicalFile();
        if (!file.getPath().startsWith(BASE.getCanonicalPath() + "/"))
            throw new IOException("Icon outside config directory");
        if (!file.isFile() || file.length() > 2097152) throw new IOException("Invalid icon: " + path);
        return file;
    }

    private static Bitmap image(String path) throws Exception {
        File file = imageFile(path);
        BitmapFactory.Options bounds = new BitmapFactory.Options();
        bounds.inJustDecodeBounds = true;
        BitmapFactory.decodeFile(file.getPath(), bounds);
        if (bounds.outWidth < 1 || bounds.outHeight < 1 || bounds.outWidth > 512 || bounds.outHeight > 512)
            throw new IOException("Icon must be at most 512x512: " + path);
        Bitmap bitmap = BitmapFactory.decodeFile(file.getPath());
        if (bitmap == null) throw new IOException("Cannot decode icon: " + path);
        return bitmap;
    }

    private static synchronized void load() {
        try {
            if (CONFIG.length() > LIMIT) throw new IOException("Config too large");
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            FileInputStream input = new FileInputStream(CONFIG);
            try {
                byte[] block = new byte[4096];
                int count;
                while ((count = input.read(block)) != -1) {
                    if (bytes.size() + count > LIMIT) throw new IOException("Config too large");
                    bytes.write(block, 0, count);
                }
            } finally { input.close(); }
            JSONObject root = new JSONObject(new String(bytes.toByteArray(), "UTF-8"));
            if (root.getInt("version") != 1) throw new IOException("Unsupported configuration version");
            String newTheme = root.optString("theme", "auto");
            if (!Arrays.asList("auto", "day", "night").contains(newTheme)) throw new IOException("Unknown theme");
            JSONArray entries = root.getJSONArray("tiles");
            if (entries.length() > 32) throw new IOException("At most 32 custom tiles");
            List<Tile> parsed = new ArrayList<Tile>();
            Map<Integer, Tile> keys = new HashMap<Integer, Tile>();
            Set<String> ids = new HashSet<String>();
            for (int i = 0; i < entries.length(); i++) {
                JSONObject entry = entries.getJSONObject(i);
                Tile tile = new Tile();
                tile.id = entry.getString("id");
                if (!tile.id.matches("[a-z][a-z0-9_]{0,47}") || !ids.add(tile.id))
                    throw new IOException("Invalid or duplicate tile ID");
                tile.name = entry.getString("display_name");
                if (tile.name.length() < 1 || tile.name.length() > 80) throw new IOException("Invalid label");
                byte[] hash = MessageDigest.getInstance("SHA-256").digest(tile.id.getBytes("UTF-8"));
                tile.key = 0x7e000000 | ((hash[0] & 255) << 16) | ((hash[1] & 255) << 8) | (hash[2] & 252);
                if (keys.containsKey(tile.key)) throw new IOException("Tile ID hash collision; choose a different ID");
                tile.day = image(entry.getString("icon_day"));
                tile.night = entry.has("icon_night") ? image(entry.getString("icon_night")) : tile.day;
                JSONObject action = entry.getJSONObject("action");
                tile.type = action.getString("type");
                if (tile.type.equals("activity")) {
                    tile.component = ComponentName.unflattenFromString(action.getString("component"));
                    if (tile.component == null) throw new IOException("Invalid component");
                } else if (tile.type.equals("exec")) {
                    JSONArray argv = action.getJSONArray("argv");
                    if (argv.length() < 1 || argv.length() > 32) throw new IOException("Invalid argv length");
                    tile.argv = new String[argv.length()];
                    for (int a = 0; a < argv.length(); a++) {
                        tile.argv[a] = argv.getString(a);
                        if (tile.argv[a].indexOf('\0') >= 0 || tile.argv[a].length() > 4096)
                            throw new IOException("Invalid command argument");
                    }
                    if (!tile.argv[0].startsWith("/")) throw new IOException("Executable must be absolute");
                    tile.toggle = action.optBoolean("toggle", true);
                } else throw new IOException("Unknown action type");
                parsed.add(tile);
                keys.put(tile.key, tile);
                keys.put(tile.key + 1, tile);
                keys.put(tile.key + 2, tile);
            }
            tiles = parsed;
            resources.clear(); resources.putAll(keys);
            theme = newTheme;
            Log.i(TAG, "Loaded " + tiles.size() + " tiles; theme=" + theme);
        } catch (Exception failure) {
            // Keep the last complete generation, or just OEM entries on first load.
            Log.e(TAG, "Config rejected; keeping " + tiles.size() + " previous tiles", failure);
        }
    }

    public static void append(Object owner) {
        try {
            boolean editor = owner.getClass().getName().equals("com.hkmc.system.app.homesetting.allmenuedit.z");
            Field contextField = owner.getClass().getDeclaredField("mContext");
            Field listField;
            if (editor) {
                try { listField = owner.getClass().getDeclaredField("cu"); }
                catch (NoSuchFieldException physical) { listField = owner.getClass().getDeclaredField("cs"); }
            } else listField = owner.getClass().getDeclaredField("by");
            contextField.setAccessible(true); listField.setAccessible(true);
            Context context = (Context) contextField.get(owner);
            List<Object> entries = (List<Object>) listField.get(owner);
            if (context == null || entries == null) return;
            application = context.getApplicationContext();
            load();
            Class<?> entry = Class.forName(editor
                ? "com.hkmc.system.app.homesetting.allmenuedit.c" : "com.android.launcher3.view.a.Q");
            Constructor<?> constructor = entry.getConstructor(owner.getClass(), Context.class,
                String.class, String.class, int.class, int.class, int.class);
            for (Tile tile : tiles) {
                if (tile.component != null) {
                    try {
                        ActivityInfo info = context.getPackageManager().getActivityInfo(tile.component, 0);
                        if (!info.enabled || !info.applicationInfo.enabled || !info.exported) continue;
                    } catch (android.content.pm.PackageManager.NameNotFoundException absent) { continue; }
                }
                boolean duplicate = false;
                for (Object existing : entries) {
                    if (PACKAGE.equals(entry.getMethod("getPackageName").invoke(existing)) &&
                        tile.id.equals(entry.getMethod("getClassName").invoke(existing))) duplicate = true;
                }
                if (!duplicate) {
                    entries.add(constructor.newInstance(owner, context, PACKAGE, tile.id,
                        tile.key + 1, tile.key + 2, tile.key));
                    Log.i(TAG, "Added " + tile.id + " to " + (editor ? "editor" : "launcher"));
                }
            }
        } catch (Exception failure) { Log.e(TAG, "Could not extend menu", failure); }
    }

    private static synchronized Tile resource(int id) { return resources.get(id); }
    public static String contextString(Context context, int id) {
        Tile tile = resource(id); return tile == null ? context.getString(id) : tile.name;
    }
    public static String resourceString(Resources resources, int id) {
        Tile tile = resource(id); return tile == null ? resources.getString(id) : tile.name;
    }
    public static CharSequence resourceText(Resources resources, int id) {
        Tile tile = resource(id); return tile == null ? resources.getText(id) : tile.name;
    }
    public static void setText(TextView view, int id) {
        Tile tile = resource(id); if (tile == null) view.setText(id); else view.setText(tile.name);
    }
    public static Drawable drawable(Resources resources, int id) {
        Tile tile = resource(id);
        return tile == null ? resources.getDrawable(id) : new TileIcon(resources, tile, id == tile.key + 2);
    }
    public static void setImageResource(ImageView view, int id) {
        Tile tile = resource(id);
        if (tile == null) view.setImageResource(id); else view.setImageDrawable(drawable(view.getResources(), id));
    }
    public static Bitmap decodeResource(Resources resources, int id) {
        Tile tile = resource(id);
        return tile == null ? BitmapFactory.decodeResource(resources, id) : selected(resources, tile);
    }
    private static Bitmap selected(Resources resources, Tile tile) {
        boolean night = theme.equals("night") || (theme.equals("auto") &&
            (resources.getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES);
        return night ? tile.night : tile.day;
    }
    private static final class TileIcon extends Drawable implements Runnable {
        final Resources resources;
        final Tile tile;
        final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG | Paint.FILTER_BITMAP_FLAG);
        final boolean disabled;
        TileIcon(Resources r, Tile t, boolean d) { resources = r; tile = t; disabled = d; setAlpha(255); }
        public int getIntrinsicWidth() { return 144; }
        public int getIntrinsicHeight() { return 144; }
        public int getOpacity() { return PixelFormat.TRANSLUCENT; }
        public void setAlpha(int alpha) { paint.setAlpha(disabled ? alpha / 2 : alpha); invalidateSelf(); }
        public void setColorFilter(ColorFilter filter) { paint.setColorFilter(filter); invalidateSelf(); }
        public void draw(Canvas canvas) {
            canvas.drawBitmap(selected(resources, tile), null, getBounds(), paint);
            if (isVisible() && getCallback() != null) scheduleSelf(this, SystemClock.uptimeMillis() + 1000);
        }
        public void run() { invalidateSelf(); }
        public boolean setVisible(boolean visible, boolean restart) {
            if (!visible) unscheduleSelf(this);
            return super.setVisible(visible, restart);
        }
    }

    /** Preserve OEM activity dispatch, intercepting only our synthetic components. */
    public static void launch(Intent intent) {
        try {
            ComponentName component = intent == null ? null : intent.getComponent();
            if (component == null || !PACKAGE.equals(component.getPackageName())) { oemLaunch(intent); return; }
            Tile target = null;
            for (Tile tile : tiles) if (tile.id.equals(component.getClassName())) target = tile;
            if (target == null) throw new IOException("Tile is no longer configured");
            if (target.component != null) {
                oemLaunch(new Intent(intent).setComponent(target.component));
            } else {
                synchronized (jobs) {
                    Job active = jobs.get(target.id);
                    if (active != null) {
                        if (target.toggle) { active.stop(); toast("Stopping " + target.name); }
                        else toast(target.name + " is already running");
                        return;
                    }
                    Job job = new Job(target);
                    jobs.put(target.id, job);
                    new Thread(job, "Gen5wTile-" + target.id).start();
                    toast("Starting " + target.name + " — tap again to stop");
                }
            }
        } catch (Exception failure) { Log.e(TAG, "Tile action failed", failure); toast("Tile action failed; see Gen5wTiles log"); }
    }
    private static void oemLaunch(Intent intent) throws Exception {
        Class.forName("com.android.launcher3.utils.a").getMethod("b", Intent.class).invoke(null, intent);
    }
    private static void toast(final String text) {
        if (application == null) return;
        new Handler(Looper.getMainLooper()).post(new Runnable() {
            public void run() { Toast.makeText(application, text, Toast.LENGTH_SHORT).show(); }
        });
    }
    private static final class Job implements Runnable {
        final Tile tile;
        java.lang.Process process;
        boolean stopping;
        int childPid;
        Job(Tile t) { tile = t; }
        synchronized void stop() {
            stopping = true;
            if (childPid == 0 || process == null) return;
            try {
                try { process.exitValue(); return; }
                catch (IllegalThreadStateException running) { /* Still our live child. */ }
                // Android 4.4 Process.destroy() sends SIGKILL, bypassing shell traps.
                // The captured framework exposes this public hidden native method.
                android.os.Process.class.getMethod("sendSignal", int.class, int.class).invoke(null, childPid, 15);
            } catch (Exception failure) { Log.e(TAG, "Could not signal " + tile.id, failure); }
        }
        public void run() {
            try {
                File output = new File(application.getFilesDir(), "tile-" + tile.id + ".log");
                synchronized (this) {
                    if (stopping) return;
                    List<String> command = new ArrayList<String>();
                    Collections.addAll(command, "/system/bin/sh", "-c", "echo GEN5W_CHILD_PID=$$; exec \"$@\"", "gen5w-tile");
                    Collections.addAll(command, tile.argv);
                    ProcessBuilder builder = new ProcessBuilder(command).directory(BASE).redirectErrorStream(true);
                    builder.environment().put("TMPDIR", application.getCacheDir().getAbsolutePath());
                    process = builder.start();
                    process.getOutputStream().close();
                }
                Log.i(TAG, "Started " + tile.id + " uid=" + android.os.Process.myUid() + " log=" + output);
                BufferedReader stream = new BufferedReader(new InputStreamReader(process.getInputStream(), "UTF-8"));
                String header = stream.readLine();
                if (header == null || !header.matches("GEN5W_CHILD_PID=[0-9]+"))
                    throw new IOException("Child PID handshake failed");
                synchronized (this) {
                    childPid = Integer.parseInt(header.substring("GEN5W_CHILD_PID=".length()));
                    if (stopping) stop();
                }
                Writer log = new OutputStreamWriter(new FileOutputStream(output), "UTF-8");
                try {
                    char[] buffer = new char[4096];
                    int count, written = 0;
                    while ((count = stream.read(buffer)) != -1) {
                        int keep = Math.min(count, 1048576 - written);
                        if (keep > 0) { log.write(buffer, 0, keep); log.flush(); written += keep; }
                    }
                } finally { log.close(); stream.close(); }
                int result = process.waitFor();
                Log.i(TAG, "Exited " + tile.id + " status=" + result);
                toast(tile.name + " exited (" + result + ")");
            } catch (Exception failure) {
                stop();
                Log.e(TAG, "Command failed: " + tile.id, failure); toast("Command failed: " + tile.name);
            } finally {
                synchronized (jobs) { if (jobs.get(tile.id) == this) jobs.remove(tile.id); }
            }
        }
    }
}
