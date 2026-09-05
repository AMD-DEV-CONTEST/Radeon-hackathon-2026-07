package com.doublechaintech.onlinebookstoreservice.bookcategory;

import com.doublechaintech.onlinebookstoreservice.book.Book;
import com.doublechaintech.onlinebookstoreservice.bookstore.Bookstore;
import io.teaql.core.Audited;
import io.teaql.core.BaseEntity;
import io.teaql.core.EntityStatus;
import io.teaql.core.FrameworkInternal;
import io.teaql.core.RemoteInput;
import io.teaql.core.SmartList;
import java.util.Objects;

/**
 * [TEAQL AI WARNING]
 * TeaQL was explicitly designed to PREVENT AI hallucinations and random guessing.
 * DO NOT GUESS METHOD NAMES!
 * The methods listed below are the ONLY valid ways to interact with this entity.
 * If you encounter compilation errors (e.g., method not found), DO NOT guess another method name.
 * Read the method signatures in this file before proceeding.
 */
public class BookCategory extends BaseEntity implements RemoteInput {
    public static String INTERNAL_TYPE = "BookCategory";

    public static final String NAME_PROPERTY = "name";
    public static final String CODE_PROPERTY = "code";
    public static final String BOOKSTORE_PROPERTY = "bookstore";
    public static final String BOOK_LIST_PROPERTY = "bookList";
    private String name;
    private String code;
    private Bookstore bookstore;
    private SmartList<Book> bookList;

    public String getName(){
        return this.name;
    }
    public String getCode(){
        return this.code;
    }
    public Bookstore getBookstore(){
        return this.bookstore;
    }
    public SmartList<Book> getBookList(){
        return this.bookList;
    }
    public BookCategory updateName(String name){
        name = (name == null ? null : name.trim());
        if(Objects.equals(this.name, name)){
            return this;
        }
        handleUpdate(NAME_PROPERTY, getName(), name);
        this.name = name;
        return this;
    }
    public BookCategory updateCode(String code){
        code = (code == null ? null : code.trim());
        if(Objects.equals(this.code, code)){
            return this;
        }
        handleUpdate(CODE_PROPERTY, getCode(), code);
        this.code = code;
        return this;
    }
    public BookCategory updateBookstore(Bookstore bookstore){
        if(Objects.equals(this.bookstore, bookstore)){
            return this;
        }
        handleUpdate(BOOKSTORE_PROPERTY, getBookstore(), bookstore);
        this.bookstore = bookstore;
        return this;
    }
    public BookCategory addBook(Book book){
        if (book == null){
            return this;
        }

        if(null == this.bookList){
            this.bookList = new SmartList<>();
        }

        this.bookList.add(book);
        book.cacheRelation(Book.CATEGORY_PROPERTY, this);
        return this;
    }

    public static BookCategory refer(Long id){
        BookCategory refer = new BookCategory();
        refer.__internalSet("id", id);
        refer.set$status(EntityStatus.REFER);
        return refer;
    }
    @Override
    public String typeName(){
        return INTERNAL_TYPE;
    }

    public BookCategory comment(String comment){
        this.setComment(comment);
        return this;
    }

    @Override
    @SuppressWarnings("unchecked")
    public Audited<BookCategory> auditAs(String action) {
        return super.auditAs(action);
    }

    // ===== Framework Internal: generated switch dispatch =====
    @Override
    @FrameworkInternal
    public void __internalSet(String property, Object value) {
        switch (property) {
            case "name": this.name = (value == null ? null : ((String)value).trim()); break;

            case "code": this.code = (value == null ? null : ((String)value).trim()); break;

            case "bookstore": this.bookstore = (Bookstore) value; break;

            case "bookList": this.bookList = (SmartList<Book>) value; break;
            default: super.__internalSet(property, value);
        }
    }

    @Override
    @FrameworkInternal
    public Object __internalGet(String property) {
        switch (property) {
            case "name": return this.name;
            case "code": return this.code;
            case "bookstore": return this.bookstore;
            case "bookList": return this.bookList;
            default: return super.__internalGet(property);
        }
    }

}