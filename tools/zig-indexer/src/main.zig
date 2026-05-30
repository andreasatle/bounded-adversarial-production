const std = @import("std");
const Ast = std.zig.Ast;
const Node = Ast.Node;

const Item = struct {
    kind: []const u8,
    name: []const u8,
    is_pub: bool,
    signature: []const u8,
    doc: ?[]const u8,
    is_test: bool,
    body_start: u32,
    body_end: u32,
};

pub fn main(init: std.process.Init) !void {
    // Use arena for all allocations: freed by the runtime after main returns,
    // avoiding DebugAllocator leak reports for duped strings and the item list.
    const allocator = init.arena.allocator();
    const io = init.io;

    var in_buf: [8192]u8 = undefined;
    var stdin_fr = std.Io.File.stdin().reader(io, &in_buf);
    const source: [:0]u8 = try stdin_fr.interface.allocRemainingAlignedSentinel(
        allocator,
        std.Io.Limit.limited(10 * 1024 * 1024),
        .@"1",
        0,
    );

    var tree = try Ast.parse(allocator, source, .zig);
    defer tree.deinit(allocator);

    var items: std.ArrayList(Item) = .empty;

    try collectItems(allocator, &tree, &items);

    var out_buf: [65536]u8 = undefined;
    var stdout_fw = std.Io.File.stdout().writer(io, &out_buf);
    const w = &stdout_fw.interface;

    try w.writeAll("{\"items\":[");
    for (items.items, 0..) |item, i| {
        if (i > 0) try w.writeByte(',');
        try writeItemJson(w, item);
    }
    try w.writeAll("]}\n");
    try stdout_fw.flush();
}

fn collectItems(
    allocator: std.mem.Allocator,
    tree: *const Ast,
    items: *std.ArrayList(Item),
) !void {
    for (tree.rootDecls()) |node_idx| {
        const tag = tree.nodeTag(node_idx);
        const first_tok = tree.firstToken(node_idx);
        const last_tok = tree.lastToken(node_idx);
        const is_pub = tree.tokenTag(first_tok) == .keyword_pub;

        switch (tag) {
            .fn_decl => {
                // data is node_and_node: [proto, body]
                const fn_tok = tree.nodeMainToken(node_idx); // fn keyword
                const name_tok = fn_tok + 1;
                if (tree.tokenTag(name_tok) != .identifier) continue;

                const body = tree.nodeData(node_idx).node_and_node[1];
                const body_first = tree.firstToken(body);
                const body_last = tree.lastToken(body);

                const sig = try allocator.dupe(u8, std.mem.trimEnd(
                    u8,
                    tree.source[tree.tokenStart(first_tok)..tree.tokenStart(body_first)],
                    " \t\n\r",
                ));
                const name = try allocator.dupe(u8, tree.tokenSlice(name_tok));
                const doc = try extractDoc(allocator, tree, first_tok);

                try items.append(allocator, .{
                    .kind = "fn",
                    .name = name,
                    .is_pub = is_pub,
                    .signature = sig,
                    .doc = doc,
                    .is_test = false,
                    .body_start = byteToLine(tree.source, tree.tokenStart(body_first)),
                    .body_end = byteToLine(tree.source, tree.tokenStart(body_last)),
                });
            },

            .test_decl => {
                // data is opt_token_and_node: [opt_name_tok, body]
                const data = tree.nodeData(node_idx).opt_token_and_node;
                const body = data[1];
                const body_first = tree.firstToken(body);
                const body_last = tree.lastToken(body);

                const name = blk: {
                    if (data[0].unwrap()) |name_tok| {
                        const raw = tree.tokenSlice(name_tok);
                        if (tree.tokenTag(name_tok) == .string_literal and raw.len >= 2) {
                            break :blk try allocator.dupe(u8, raw[1 .. raw.len - 1]);
                        } else if (tree.tokenTag(name_tok) == .identifier) {
                            break :blk try allocator.dupe(u8, raw);
                        }
                    }
                    break :blk try allocator.dupe(u8, "unnamed");
                };

                const sig = try allocator.dupe(u8, std.mem.trimEnd(
                    u8,
                    tree.source[tree.tokenStart(first_tok)..tree.tokenStart(body_first)],
                    " \t\n\r",
                ));
                const doc = try extractDoc(allocator, tree, first_tok);

                try items.append(allocator, .{
                    .kind = "fn",
                    .name = name,
                    .is_pub = false,
                    .signature = sig,
                    .doc = doc,
                    .is_test = true,
                    .body_start = byteToLine(tree.source, tree.tokenStart(body_first)),
                    .body_end = byteToLine(tree.source, tree.tokenStart(body_last)),
                });
            },

            .simple_var_decl,
            .aligned_var_decl,
            .global_var_decl,
            => {
                const kw_tok = tree.nodeMainToken(node_idx); // const or var
                const name_tok = kw_tok + 1;
                if (tree.tokenTag(name_tok) != .identifier) continue;

                const name = try allocator.dupe(u8, tree.tokenSlice(name_tok));

                const opt_init = getOptInit(tag, tree, node_idx);
                const kind: []const u8 = if (opt_init) |init_node|
                    kindFromMainToken(tree.tokenTag(tree.nodeMainToken(init_node)))
                else
                    "const";

                // Find opening brace for body_start
                var lbrace_tok: ?Ast.TokenIndex = null;
                {
                    var t = name_tok;
                    while (t <= last_tok) : (t += 1) {
                        if (tree.tokenTag(t) == .l_brace) {
                            lbrace_tok = t;
                            break;
                        }
                    }
                }

                const sig_end = if (lbrace_tok) |lt| tree.tokenStart(lt) else tree.tokenStart(last_tok);
                const sig_raw = std.mem.trimEnd(u8, tree.source[tree.tokenStart(first_tok)..sig_end], " \t\n\r=");
                const sig = try allocator.dupe(u8, std.mem.trimEnd(u8, sig_raw, " \t\n\r"));

                const body_start_line = if (lbrace_tok) |lt|
                    byteToLine(tree.source, tree.tokenStart(lt))
                else
                    byteToLine(tree.source, tree.tokenStart(first_tok));

                const doc = try extractDoc(allocator, tree, first_tok);

                try items.append(allocator, .{
                    .kind = kind,
                    .name = name,
                    .is_pub = is_pub,
                    .signature = sig,
                    .doc = doc,
                    .is_test = false,
                    .body_start = body_start_line,
                    .body_end = byteToLine(tree.source, tree.tokenStart(last_tok)),
                });
            },

            else => {},
        }
    }
}

fn getOptInit(tag: Node.Tag, tree: *const Ast, node_idx: Node.Index) ?Node.Index {
    return switch (tag) {
        .simple_var_decl => tree.nodeData(node_idx).opt_node_and_opt_node[1].unwrap(),
        .aligned_var_decl => tree.nodeData(node_idx).node_and_opt_node[1].unwrap(),
        .global_var_decl => tree.nodeData(node_idx).extra_and_opt_node[1].unwrap(),
        else => null,
    };
}

fn kindFromMainToken(tok_tag: std.zig.Token.Tag) []const u8 {
    return switch (tok_tag) {
        .keyword_struct => "struct",
        .keyword_enum => "enum",
        .keyword_union => "union",
        else => "const",
    };
}

fn byteToLine(source: [:0]const u8, offset: u32) u32 {
    var line: u32 = 1;
    const end = @min(offset, @as(u32, @intCast(source.len)));
    for (source[0..end]) |c| {
        if (c == '\n') line += 1;
    }
    return line;
}

fn extractDoc(
    allocator: std.mem.Allocator,
    tree: *const Ast,
    first_tok: Ast.TokenIndex,
) !?[]const u8 {
    if (first_tok == 0) return null;
    var i = first_tok;
    while (i > 0) {
        i -= 1;
        if (tree.tokenTag(i) != .doc_comment) break;
        // Find earliest consecutive doc_comment block
        var start = i;
        while (start > 0 and tree.tokenTag(start - 1) == .doc_comment) {
            start -= 1;
        }
        const slice = tree.tokenSlice(start);
        // slice = "/// text" — skip "///" and trim
        const text = std.mem.trim(u8, if (slice.len > 3) slice[3..] else "", " ");
        if (text.len > 0) return try allocator.dupe(u8, text);
        return null;
    }
    return null;
}

fn writeItemJson(w: *std.Io.Writer, item: Item) !void {
    try w.writeAll("{");
    try writeJsonKV(w, "kind", item.kind);
    try w.writeByte(',');
    try writeJsonKV(w, "name", item.name);
    try w.writeByte(',');
    try w.writeAll("\"pub\":");
    try w.writeAll(if (item.is_pub) "true" else "false");
    try w.writeByte(',');
    try writeJsonKV(w, "signature", item.signature);
    try w.writeByte(',');
    try w.writeAll("\"doc\":");
    if (item.doc) |d| try writeJsonStr(w, d) else try w.writeAll("null");
    try w.writeByte(',');
    try w.writeAll("\"is_test\":");
    try w.writeAll(if (item.is_test) "true" else "false");
    try w.writeByte(',');
    try w.print("\"body_start\":{d},\"body_end\":{d}", .{ item.body_start, item.body_end });
    try w.writeByte('}');
}

fn writeJsonKV(w: *std.Io.Writer, key: []const u8, value: []const u8) !void {
    try writeJsonStr(w, key);
    try w.writeByte(':');
    try writeJsonStr(w, value);
}

fn writeJsonStr(w: *std.Io.Writer, s: []const u8) !void {
    try w.writeByte('"');
    for (s) |c| {
        switch (c) {
            '"' => try w.writeAll("\\\""),
            '\\' => try w.writeAll("\\\\"),
            '\n' => try w.writeAll("\\n"),
            '\r' => try w.writeAll("\\r"),
            '\t' => try w.writeAll("\\t"),
            else => try w.writeByte(c),
        }
    }
    try w.writeByte('"');
}
